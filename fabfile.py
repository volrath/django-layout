"""

This fabric file makes setting up and deploying a django
application much easier, but it does make a few assumptions. Namely
that you're using Git, Nginx and your using Debian or Ubuntu.

"""

import json, os
from contextlib import nested
from datetime import datetime

from fabric.api import (append, cd, env, execute, exists, hide, lcd, local,
                        prefix, prompt, put, puts, roles, run, settings, sudo,
                        task)
from fabric.colors import cyan, green, red


# GLOBALS
# ------------------------------------------------------------------------------
env.project_name = '{{ project_name }}'

env.repository = 'git@git.talpor.com:{{ project_name }}.git'
env.local_branch = 'master'
env.remote_ref = 'origin/master'

env.requirements_file = 'requirements.pip'

env.project_path = '/home/{project_name}/{project_name}/'.format(**env)
env.venv_path = '/home/{project_name}/.virtualenvs/{project_name}'.format(**env)

env.restart_command = 'supervisorctl restart {project_name}'.format(**env)
env.restart_sudo = True

# env.forward_agent = True


#===============================================================================
# Tasks which set up deployment environments
#===============================================================================

@task
def prod():
    """Use the production deployment environment."""
    env.site_url = '{{ project_name }}.com'
    env.roledefs = {
        'web': [env.site_url],
        'db': [env.site_url],
    }
    env.system_users = {env.site_url: env.project_name}
    env.project_settings = '{project_name}.settings.prod'.format(**env)

@task
def dev():
    """Use the development deployment environment."""
    env.site_url = '{{ project_name }}.talpor.com'
    env.roledefs = {
        'web': [env.site_url],
        'db': [env.site_url],
    }
    env.system_users = {env.site_url: env.project_name}
    env.project_conf = '{project_name}.conf.dev'.format(**env)


# Set the default environment.
dev()


#===============================================================================
# Actual tasks
#===============================================================================

# BOOTSTRAPPING
# ------------------------------------------------------------------------------
def bootstrap():
    print(cyan('Starting Bootstrap...', bold=True))
    sudo('apt-get -q -y update')
    sudo('apt-get -q -y upgrade')
    sudo('apt-get -q -y install ssl-cert ruby ruby-dev libopenssl-ruby '
         'build-essential rubygems ruby-bundler')
    sudo('gem install chef --no-ri --no-rdoc')

def provision():
    project_root = os.path.dirname(env.real_fabfile)
    chef_root = os.path.join(project_root, 'bootstrap')
    chef_name = 'chef-{0}'.format(datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S'))
    chef_archive = '{0}.tar.gz'.format(chef_name)
    local('cp -r {0} /tmp/{1}'.format(chef_root, chef_name))

    with open(os.path.join(chef_root, 'nodes', '%s.json' % env.settings)) as f:
        data = json.load(f)
    project = data.setdefault('project', {})
    project['environment'] = env.settings
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
    execute('initial_deploy')
    print(cyan('Restarting nginx...', bold=True))
    sudo('service nginx restart')
    check()

def initial_deploy(action=''):
    # clone repo
    env.run('chmod 711 /home/{project_name}'.format(**env))

    if not exists(os.path.join(env.project_path, '.git')):
        with cd(os.path.dirname(os.path.abspath(env.project_path))):
            # avoid ssh asking us to verify the fingerprint
            append('/home/%s/.ssh/config' % env.project_name,
                   'Host talpor.com\n\tStrictHostKeyChecking no\n')
            print(cyan('Cloning Repo...', bold=True))
            env.run('git clone %s %s' % (env.project_repo, env.project_name))
    else:
        print(cyan('Repository already cloned', bold=True))

    # start virtualenv
    if not exists(env.venv_path):
        print(cyan('Creating Virtualenv...', bold=True))
        run('virtualenv %s' % env.venv_path)
        with cd(env.project_path):
            run('cat "export GEM_HOME=\"$VIRTUAL_ENV/gems\"" >> '  #
                '{venv_path}/postactivate'.format(**env))          # Maybe we should
            run('cat "export GEM_PATH=\"\"" >> '                   # move these to
                '{venv_path}/postactivate'.format(**env))          # chef.
            run('bundle install --path vendor/bundle')             #
    else:
        print(cyan('Virtualenv already exists', bold=True))

    # set owners and modes
    # FIXME: I think this is not required anymore -- jcc
    env.run('chown {project_name}:{project_name} -R {project_path}'\
            .format(**env))
    env.run('chown {0}:{0} -R {1}'\
            .format(env.project_name,
                    os.path.dirname(os.path.abspath(env.venv_path))))
    env.run('chmod 755 {venv_path}'.format(**env))
    env.run('chmod 755 {venv_path}'.format(**env))

    print(cyan('Deploying...', bold=True))
    deploy()

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
# ------------------------------------------------------------------------------

@task
@roles('web', 'db')
def cmd(cmd=""):
    """Run a command in the site directory.  Usable from other
    commands or the CLI.
    """
    if not cmd:
        print(cyan("Command to run: "))
        cmd = raw_input().strip()
    if cmd:
        with nested(cd(env.site_path),
                    prefix('workon {project_name}'.format(**env))):
            env.run(cmd)

@task
@roles('web', 'db')
def manage_py(mcmd):
    """Returns a string for a manage.py command execution."""
    if not cmd:
        print(cyan("./manage.py: "))
        mcmd = raw_input().strip()
    if mcmd:
        return cmd(mcmd + ' --settings={project_settings}'.format(**env))


# PROJECT MAINTENANCE
# ------------------------------------------------------------------------------
@task
def deploy(verbosity='normal'):
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
        execute(update)
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
            reqs_changed = env.requirements_file in changed_files  # FIX: check for '.pip' files
            stylesheets_changed = ''  # Fix: check for '.scss' or '.sass' files.
        else:
            reqs_changed = False
            stylesheets_changed = False

        run('git merge {remote_ref}'.format(**env))
        run('find -name "*.pyc" -delete')
        run('git clean -df')

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
    cmd('compass compile --time --boring -c conf/common/compass.rb')


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
def restart():
    """Restart the web service."""
    if env.restart_sudo:
        cmd = sudo
    else:
        cmd = run
    cmd(env.restart_command)
    check()

@task
@roles('web', 'db')
def requirements():
    """Update the requirements."""
    cmd('pip install -r {project_path}/requirements/{project_env}.pip'\
        .format(**env))


# HELPERS
# ------------------------------------------------------------------------------

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
