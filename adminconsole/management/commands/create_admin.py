import docker

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('password', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]
        password = options['password'][0]

        container = docker.from_env().containers.get(app_name)
        result = container.exec_run([
            'python', '-m', 'manage', 'createadmin', '--noinput'
        ], environment={
            'DJANGO_SUPERUSER_USERNAME': 'admin',
            'DJANGO_SUPERUSER_PASSWORD': password,
            'DJANGO_SUPERUSER_EMAIL': 'admin@example.com',
        })
        print(result[1])
