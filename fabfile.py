"""

This fabric file makes setting up and deploying a django
application much easier, but it does make a few assumptions. Namely
that you're using Git, Nginx and your using Debian or Ubuntu.

"""

import json, os
from contextlib import nested
from datetime import datetime

from fabric.api import (cd, env, execute, hide, lcd, local, prefix, prompt,
                        put, puts, roles, run, settings, sudo, task,
                        with_settings)
from fabric.colors import cyan, green, red
from fabric.contrib.files import append, exists


# GLOBALS
# -----------------------------------------------------------------------------
env.project_name = '{{ project_name }}'

env.repository = 'git@git.talpor.com:{{ project_name }}.git'
env.local_branch = 'master'
env.remote_ref = 'origin/master'

env.project_path = '/home/{project_name}/{project_name}'.format(**env)
env.venv_path = '/home/{project_name}/.virtualenvs/{project_name}'.format(**env)

env.restart_command = 'supervisorctl restart {project_name}'.format(**env)
env.restart_sudo = True

env.compass_config = '{project_path}/{project_name}/static/config.rb'.format(**env)

# env.forward_agent = True


#==============================================================================
# Tasks which set up deployment environments
#==============================================================================

@task
def prod():
    """Use the production deployment environment."""
    env.site_url = '{{ project_name }}.com'
    env.roledefs = {
        'web': [env.site_url],
        'db': [env.site_url],
    }
    env.system_users = {env.site_url: env.project_name}
    env.environment = 'prod'
    env.project_settings = '{project_name}.settings.{environment}'\
                           .format(**env)
    env.supervisord = '{project_path}/server/{environment}/supervisord.conf'\
                      .format(**env)

@task
def dev():
    """Use the development deployment environment."""
    env.site_url = '{{ project_name }}.talpor.com'
    env.roledefs = {
        'web': [env.site_url],
        'db': [env.site_url],
    }
    env.system_users = {env.site_url: env.project_name}
    env.environment = 'dev'
    env.project_settings = '{project_name}.settings.{environment}'\
                           .format(**env)
    env.supervisord = '{project_path}/server/{environment}/supervisord.conf'\
                      .format(**env)

@task
def vgr():
    """Use the development deployment environment."""
    env.site_url = '127.0.0.1:8888'
    env.roledefs = {
        'web': ['127.0.0.1:2222'],
        'db': ['127.0.0.1:2222'],
    }
    env.system_users = {env.site_url: env.project_name}
    env.environment = 'dev'
    env.project_settings = '{project_name}.settings.{environment}'\
                           .format(**env)
    env.supervisord = '{project_path}/server/{environment}/supervisord.conf'\
                      .format(**env)
    # use vagrant ssh key
    result = local('vagrant ssh-config | grep IdentityFile', capture=True)
    env.key_filename = result.split()[1]


# Set the default environment.
dev()


#==============================================================================
# Actual tasks
#==============================================================================

# BOOTSTRAPPING
# -----------------------------------------------------------------------------
@task
@roles('web', 'db')
def bootstrap():
    print(cyan('Starting Bootstrap...', bold=True))
    sudo('apt-get -q -y update')
    sudo('apt-get -q -y upgrade')
    sudo('apt-get -q -y install ssl-cert ruby ruby-dev libopenssl-ruby '
         'build-essential rubygems ruby-bundler')
    sudo('gem install chef --no-ri --no-rdoc')

@task
@roles('web', 'db')
def provision():
    project_root = os.path.dirname(env.real_fabfile)
    chef_root = os.path.join(project_root, 'bootstrap')
    chef_name = 'chef-{0}'.format(datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S'))
    chef_archive = '{0}.tar.gz'.format(chef_name)
    local('cp -r {0} /tmp/{1}'.format(chef_root, chef_name))

    with open(os.path.join(chef_root, 'nodes', '%s.json' % env.environment)) as f:
        data = json.load(f)
    project = data.setdefault('project', {})
    project['environment'] = env.environment
    with open('/tmp/{0}/node.json'.format(chef_name), 'w') as f:
        json.dump(data, f)

    solo_rb = ('file_cache_path "/tmp/chef-solo"',
               'cookbook_path "/tmp/{0}/cookbooks"'.format(chef_name))
    with lcd('/tmp'):
        for line in solo_rb:
            local("echo '{0}' >> {1}/solo.rb".format(line, chef_name))
        local('tar czf {0} {1}'.format(chef_archive, chef_name))

    # run chef
    put('/tmp/{0}'.format(chef_archive), '/tmp/{0}'.format(chef_archive))
    local('rm -rf /tmp/{0}*'.format(chef_name))
    with cd('/tmp'):
        sudo('tar xf {0}'.format(chef_archive))
    with cd('/tmp/{0}'.format(chef_name)):
        with settings(warn_only=True):
            print(cyan('Running Chef Solo...', bold=True))
            sudo('chef-solo -c solo.rb -j node.json')
    sudo('rm -rf /tmp/{0}*'.format(chef_name))

    print(cyan('Copying ssh key and doing initial deploy...', bold=True))
    upload_public_key()
    execute(initial_deploy)
    print(cyan('Restarting nginx...', bold=True))
    sudo('service nginx restart')
    check()

@task
@with_settings(user=env.project_name)
def initial_deploy(action=''):
    # clone repo
    run('chmod 711 /home/{project_name}'.format(**env))

    if not exists(os.path.join(env.project_path, '.git')):
        with cd(os.path.dirname(os.path.abspath(env.project_path))):
            # avoid ssh asking us to verify the fingerprint
            append('/home/%s/.ssh/config' % env.project_name,
                   'Host talpor.com\n\tStrictHostKeyChecking no\n')
            print(cyan('Cloning Repo...', bold=True))
            run('git clone %s %s' % (env.repository, env.project_name))
    else:
        print(cyan('Repository already cloned', bold=True))

    # start virtualenv
    if not exists(env.venv_path):
        print(cyan('Creating Virtualenv...', bold=True))
        run('virtualenv %s' % env.venv_path)
        if exists(os.path.join(env.project_path, 'Gemfile')):
            gem_home = '{venv_path}/gems'.format(**env)
            run('echo "export GEM_HOME=\'{gem_home}\'" >> '
                '{venv_path}/bin/postactivate'.format(gem_home=gem_home, **env))
            run('echo "export GEM_PATH=\'\'" >> '
                '{venv_path}/bin/postactivate'.format(**env))
            run('mkdir ' + gem_home)
            run('source ~/.bash_profile')
            cmd('bundle install')
    else:
        print(cyan('Virtualenv already exists', bold=True))

    print(cyan('Deploying...', bold=True))
    deploy(action='force')

def upload_public_key():
    path = prompt('Path to your public key? [~/.ssh/id_rsa.pub]') or \
           '~/.ssh/id_rsa.pub'
    path = os.path.expanduser(path)
    if os.path.exists(path):
        key = ' '.join(open(path).read().strip().split(' ')[:2])
        sudo('mkdir -p /home/{project_name}/.ssh'.format(**env))
        append('/home/{project_name}/.ssh/authorized_keys'.format(**env), key,
               partial=True, use_sudo=True)
        sudo('chown {project_name}:{project_name} '
             '/home/{project_name}/.ssh/authorized_keys'.format(**env))
        sudo('chmod 600 /home/{project_name}/.ssh/authorized_keys'\
             .format(**env))
        sudo('chown {project_name}:{project_name} /home/{project_name}/.ssh'\
             .format(**env))
        sudo('chmod 700 /home/{project_name}/.ssh'.format(**env))



# BASIC TASKS
# -----------------------------------------------------------------------------

@task
@roles('web', 'db')
def cmd(cmd='', path=None):
    """Run a command in the site directory.  Usable from other
    commands or the CLI.
    """
    if not cmd:
        cmd = prompt('Command to run:')
    if cmd:
        with nested(cd(path or env.project_path),
                    prefix('workon {project_name}'.format(**env))):
            return run(cmd)

@task
@roles('web', 'db')
def manage_py(mcmd):
    """Returns a string for a manage.py command execution."""
    if not mcmd:
        mcmd = prompt('./manage.py: ')
    if mcmd:
        return cmd('python manage.py ' + mcmd +
                   ' --settings={project_settings}'.format(**env))

@task
@roles('web', 'db')
def supervisorctl(scmd):
    """Returns a string for a supervisorctl command execution."""
    if not scmd:
        scmd = prompt('supervisorctl: ')
    if scmd:
        return cmd('supervisorctl -c {supervisord} {scmd}'\
                   .format(scmd=scmd, **env))

# PROJECT MAINTENANCE
# -----------------------------------------------------------------------------
@task
@roles('web', 'db')
def deploy(verbosity='normal', action='check'):
    """Full server deploy.

    Updates the repository (server-side), synchronizes the database, collects
    static files and then restarts the web service.
    """
    if verbosity == 'noisy':
        hide_args = []
    else:
        hide_args = ['running', 'stdout']

    with hide(*hide_args):
        puts('Updating repository...')
        execute(update, action=action)
        puts('Collecting static files...')
        execute(collectstatic)
        puts('Synchronizing database...')
        execute(syncdb)
        puts('Restarting web server...')
        execute(restart)

@task
@roles('web', 'db')
def update(action='check'):
    """Update the repository (server-side).

    By default, if the requirements file changed in the repository then the
    requirements will be updated. Use ``action='force'`` to force updating
    requirements. Anything else other than ``'check'`` will avoid updating
    requirements at all.
    """
    with cd(env.project_path):
        remote, dest_branch = env.remote_ref.split('/', 1)
        run('git fetch {remote}'.format(remote=remote,
            dest_branch=dest_branch, **env))
        with hide('running', 'stdout'):
            changed_files = run('git diff-index --cached --name-only '
                '{remote_ref}'.format(**env)).splitlines()
        if not changed_files and action != 'force':
            # No changes, we can exit now.
            return
        if action == 'check':
            reqs_changed = 'requirements/base.pip' in changed_files or \
                'requirements/{environment}.pip'.format(**env) in changed_files
            stylesheets_changed = exists(env.compass_config) and bool(filter(
                lambda f: f.endswith('.sass') or f.endswith('.scss'),
                changed_files
            ))
        else:
            reqs_changed = False
            stylesheets_changed = False

        run('git merge {remote_ref}'.format(**env))
        run('find -name "*.pyc" -delete')
        # run('git clean -df') # it deletes var.

    # Not using execute() because we don't want to run multiple times for
    # each role (since this task gets run per role).
    if action == 'force' or reqs_changed:
        requirements()
    if action == 'force' or stylesheets_changed:
        compass()

@task
@roles('web', 'db')
def compass():
    """Runs compass compile over the stylesheets."""
    cmd('bundle exec compass compile --time --boring',
        os.path.dirname(env.compass_config))


@task
@roles('web')
def collectstatic():
    """Collect static files from apps and other locations in a single location.
    """
    manage_py('collectstatic --link --noinput -v0')

@task
@roles('db')
def syncdb(sync=True, migrate=True):
    """Synchronize the database."""
    manage_py('syncdb --migrate --noinput')

@task
@roles('web')
def restart(hard=False):
    """Restart the web service."""
    with hide('running', 'stdout'):
        result = supervisorctl('status')
    if 'no such file' in result:
        cmd('supervisord -c {supervisord}'.format(**env))
    else:
        supervisorctl('restart all'.format(**env))
    if hard:
        sudo('service nginx restart')
    check()

@task
@roles('web', 'db')
def requirements():
    """Update the requirements."""
    cmd('pip install -r {project_path}/requirements/{environment}.pip'\
        .format(**env))


# HELPERS
# -----------------------------------------------------------------------------

def check():
    """Check that the home page of the site returns an HTTP 200."""
    print(cyan('Checking site status...', bold=True))
    if not '200 OK' in local('curl --silent -I "{site_url}"'.format(**env),
                             capture=True):
        _sad()
    else:
        _happy()

def _happy():
    print(green("""
          .-.
          | |
          | |   .-.
          | |-._| |
          |_| | | |
         / )|_|_|-|
        | | `-^-^ |
        |     ||  |
        \     '   /
         |       |
         |       |

    Looks good from here!
    """))

def _sad():
    print(red(r"""
          ___           ___
         /  /\         /__/\
        /  /::\        \  \:\
       /  /:/\:\        \__\:\
      /  /:/  \:\   ___ /  /::\
     /__/:/ \__\:\ /__/\  /:/\:\
     \  \:\ /  /:/ \  \:\/:/__\/
      \  \:\  /:/   \  \::/
       \  \:\/:/     \  \:\
        \  \::/       \  \:\
         \__\/         \__\/
          ___           ___
         /__/\         /  /\     ___
         \  \:\       /  /::\   /__/\
          \  \:\     /  /:/\:\  \  \:\
      _____\__\:\   /  /:/  \:\  \  \:\
     /__/::::::::\ /__/:/ \__\:\  \  \:\
     \  \:\~~\~~\/ \  \:\ /  /:/   \  \:\
      \  \:\  ~~~   \  \:\  /:/     \__\/
       \  \:\        \  \:\/:/          __
        \  \:\        \  \::/          /__/\
         \__\/         \__\/           \__\/

         Something seems to have gone wrong!
         You should probably take a look at that.
    """))
