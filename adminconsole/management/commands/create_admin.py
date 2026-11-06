import os

import docker

from django.core.management.base import BaseCommand, CommandError

from adminconsole.util.admin import ADMIN_USERNAME, PASSWORD_ENV


class Command(BaseCommand):
    help = f'Creates the admin user of the app. The password is read from the environment variable {PASSWORD_ENV}.'

    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]
        password = os.environ.get(PASSWORD_ENV)
        if not password:
            raise CommandError(f'{PASSWORD_ENV} is not set')

        container = docker.from_env().containers.get(app_name)
        result = container.exec_run(
            ['python', '-m', 'manage', 'createadmin', '--noinput'],
            environment={
                'DJANGO_SUPERUSER_USERNAME': ADMIN_USERNAME,
                'DJANGO_SUPERUSER_PASSWORD': password,
                'DJANGO_SUPERUSER_EMAIL': 'admin@example.com',
            },
        )
        print(result[1])
