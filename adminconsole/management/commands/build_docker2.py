import docker

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)
        parser.add_argument('pass', nargs=1)
        parser.add_argument('port', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        passw = options['pass'][0]
        port = options['port'][0]
        dir = '/var/django/projects/'+name
        crss = 'from django.contrib.auth.models import User; User.objects.create_superuser("admin", "admin@admin.com", "'+ passw +'")'
        runcmd = 'gunicorn --bind 0.0.0.0:'+port+' '+name+'.wsgi &'

        with open(dir+'/build/'+name+'.env') as f:
            env = f.readlines()
        env = [x.strip() for x in env] 

        client = docker.from_env()

        result = client.images.build(path=dir+'/build/',
                            tag=name+':latest')
        print(result[1])
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

        cmd = ['python', '-m', 'manage', 'migrate']
        result = container.exec_run(cmd)
        print(result[1])
        cmd = ['python', '-m', 'manage', 'shell', '-c', crss]
        result = container.exec_run(cmd)
        print(result[1])
        cmd = ['python', '-m', 'manage', 'create_member_for_superusers']
        result = container.exec_run(cmd)
        print(result[1])
        cmd = ['python', '-m', 'manage', 'collectstatic']
        result = container.exec_run(cmd)
        print(result[1])
        cmd = ['(crontab -l 2>/dev/null; echo "59 23 * * * docker exec '+name+' python -m manage generate_depot_list") | crontab -']
        result = container.exec_run(cmd)
        print(result[1])

