import subprocess
from datetime import datetime

import docker
from django.conf import settings
from django.core.management import call_command

from django.core.management.base import BaseCommand

from adminconsole.models import App, AppEnv
from adminconsole.util.commands import log_after
from adminconsole.util.create_app import create_database


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('--no-restart', action='store_true', help="Don't restart container")

    # entry point used by manage.py
    def handle(self, *args, **options):
        app = App.objects.get(name=options['app_name'][0])
        if not app.staging_of:
            raise ValueError(f'{app} must be a staging app')

        # re-create db
        if not hasattr(app, 'env'):
            app_env = AppEnv.objects.get(app=app.staging_of)
            app_env.pk = None
            app_env.app = app
            app_env.juntagrico_email_user = ''
            app_env.juntagrico_email_password = ''
        create_database(app.env, app.name, app.name, replace=True)

        # copy tables from prod app
        print('# Clone Database', flush=True)
        db_user = settings.DATABASES['default']['USER']
        db_pw = settings.DATABASES['default']['PASSWORD']
        load = subprocess.Popen(
            ['psql', '-U', db_user, '--no-password', app.env.juntagrico_database_name],
            stdin=subprocess.PIPE, stderr=subprocess.STDOUT, env={'PGPASSWORD': db_pw}
        )
        change_owner = subprocess.Popen(
            ['sed', f's/OWNER TO {app.staging_of.env.juntagrico_database_user}/OWNER TO {app.env.juntagrico_database_user}/'],
            stdout=load.stdin, stdin=subprocess.PIPE
        )
        dump = subprocess.Popen(
            ['pg_dump', '-U', db_user, '--no-password', '--no-comments', app.staging_of.env.juntagrico_database_name],
            stdout=change_owner.stdin, env={'PGPASSWORD': db_pw}
        )
        dump.communicate()
        change_owner.communicate()
        print(load.communicate(b'\q'))
        print('Return 0', flush=True)

        if not options.get('no-restart'):
            # restart docker (to pass new db pw to env)
            print('# Docker Restart', flush=True)
            call_command('restart', app.name)

            # apply migrations, because staging may use newer version of code
            print('# Django Migrate', flush=True)
            container = docker.from_env().containers.get(app.name)
            cmd = ['python', '-m', 'manage', 'migrate']
            result = container.exec_run(cmd)
            print(result[1])
            print('Return', result[0], flush=True)

            print('# Docker Restart2', flush=True)
            start = datetime.now()
            container.restart()
            print(log_after(container, since=start))
            print('Return 0', flush=True)

        return 0
