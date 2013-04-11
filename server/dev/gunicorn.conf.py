import os

def num_cpus():
    if not hasattr(os, "sysconf"):
        raise RuntimeError("No sysconf detected.")
    return os.sysconf("SC_NPROCESSORS_ONLN")

preload = True
workers = num_cpus() * 2 + 1
bind = '127.0.0.1:11000'
pid = '/home/{{ project_name }}/{{ project_name }}/var/gunicorn.pid'
django_settings = '{{ project_name }}.settings.dev'

# log files
accesslog = '/home/{{ project_name }}/{{ project_name }}/server/dev/logs/gunicorn-access.log'
errorlog  = '/home/{{ project_name }}/{{ project_name }}/server/dev/logs/gunicorn-error.log'
loglevel  = 'debug'
