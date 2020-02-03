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
        dir = '/var/django/projects/'+name
        runcmd = 'gunicorn --bind 127.0.0.1:'+port+' -t 6000  '+name+'.wsgi &'

        with open(dir+'/build/'+name+'.env') as f:
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

        container = client.containers.run(image=name+':latest',
                                       command=runcmd,
                                       detach=True,
                                       environment=env,
                                       name=name,
                                       network_mode='host',
                                       restart_policy={'Name': 'always'},
                                       volumes={dir+'/code': {'bind': '/code/',
                                                           'mode': 'rw'},
                                                dir+'/static': {'bind': '/code/static/',
                                                             'mode': 'rw'},
                                                dir+'/media': {'bind': '/code/media/',
                                                            'mode': 'rw'},
                                               }
                                        )

