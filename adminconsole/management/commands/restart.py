import docker

from django.core.management.base import BaseCommand

from adminconsole.models import App


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)
        parser.add_argument('port', nargs='?')

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        port = options['port'] or App.objects.get(name=name).port
        base_dir = '/var/django/projects/'+name

        with open(base_dir+'/build/'+name+'.env') as f:
            env = f.readlines()
        env = [x.strip() for x in env]
        env = [x for x in env if x]

        client = docker.from_env()

        try:
            container = client.containers.get(name)
            container.stop()
            container.remove()
        except:
            print('container not found or other error')

        container = client.containers.run(
            image=name + ':latest',
            detach=True,
            environment=env,
            name=name,
            ports={'80': ('127.0.0.1', port)},
            extra_hosts={"host.docker.internal": "172.17.0.1"},
            restart_policy={'Name': 'always'},
            volumes={
                base_dir + '/code': {'bind': '/code/', 'mode': 'rw'},
                base_dir + '/static': {'bind': '/code/static/', 'mode': 'rw'},
                base_dir + '/media': {'bind': '/code/media/', 'mode': 'rw'},
            }
        )
        print(container.status)
