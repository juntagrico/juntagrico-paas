import subprocess

import docker

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('port', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        port = options['port'][0]
        dir = '/var/django/projects/' + name
        bdir = dir + '/build'
        cdir = dir + '/code'
        req = cdir + '/requirements.txt'
        runcmd = 'gunicorn --bind 127.0.0.1:' + port + ' -t 6000 ' + name + '.wsgi &'

        with open(bdir + '/' + name + '.env') as f:
            env = f.readlines()
        env = [x.strip() for x in env]
        env = [x for x in env if x]

        print('# Git Fetch & Reset', flush=True)
        # get latest requirements.txt
        proc1 = subprocess.run(['git', 'fetch'], cwd=cdir)
        proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], cwd=cdir)
        proc3 = subprocess.run(['cp', req, bdir], cwd=bdir)
        print('Return ', proc1.returncode + proc2.returncode + proc3.returncode, flush=True)

        print('# Docker Build', flush=True)
        client = docker.from_env()
        result = client.images.build(path=bdir + '/', tag=name + ':latest')
        for line in result[1]:
            print(line.get('stream') or (str(line) + '\n'), sep="")
        print('Return 0', flush=True)

        try:
            print('# Docker Stop', flush=True)
            container = client.containers.get(name)
            container.stop()
            container.remove()
            print('Stopped ', name)
            print('Return 0', flush=True)
        except:
            print('container not found or other error')

        print('# Docker Run', flush=True)
        container = client.containers.run(
            image=name + ':latest',
            command=runcmd,
            detach=True,
            environment=env,
            name=name,
            network_mode='host',
            restart_policy={'Name': 'always'},
            volumes={
                dir + '/code': {'bind': '/code/', 'mode': 'rw'},
                dir + '/static': {'bind': '/code/static/', 'mode': 'rw'},
                dir + '/media': {'bind': '/code/media/', 'mode': 'rw'},
            }
        )
        container.exec_run(['python', '--version'])  # make sure container is ready
        print(container.logs())
        print(container.status)
        print('Return 0', flush=True)

        print('# Django Migrate', flush=True)
        cmd = ['python', '-m', 'manage', 'migrate']
        result = container.exec_run(cmd)
        print(result[1])
        print('Return ', result[0], flush=True)
        print('# Django Collectstatic', flush=True)
        cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
        result = container.exec_run(cmd)
        print(result[1])
        print('Return ', result[0], flush=True)

        print('# Docker Restart', flush=True)
        container.restart()
        container.exec_run(['python', '--version'])  # make sure container is ready
        print(container.logs())
        print('Return 0', flush=True)
