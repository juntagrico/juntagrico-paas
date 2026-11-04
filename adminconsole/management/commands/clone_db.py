import subprocess

from django.conf import settings

from django.core.management import call_command
from django.core.management.base import BaseCommand

from adminconsole.util.docker import _run_migration_in_temp_container
from adminconsole.models import App, AppEnv
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
        target_user = app.env.juntagrico_database_user
        load = subprocess.Popen(
            ['psql', '-U', target_user, '--no-password', app.env.juntagrico_database_name],
            stdin=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={'PGPASSWORD': app.env.juntagrico_database_password}
        )
        source_user = app.staging_of.env.juntagrico_database_user
        dump = subprocess.Popen(
            ['pg_dump', '-U', source_user, '--no-password', '--no-comments', '--no-owner', '--no-privileges',
             app.staging_of.env.juntagrico_database_name],
            stdout=load.stdin, env={'PGPASSWORD': app.staging_of.env.juntagrico_database_password}
        )
        dump.communicate()
        load.communicate(b'\\q')
        print('Return 0', flush=True)

        if not options.get('no_restart'):
            # apply migrations in a temporary container with the latest environment
            print('# Django Migrate', flush=True)
            result = _run_migration_in_temp_container(app, app.name)
            print('Return', result, flush=True)

            # restart to pick up the new db credentials
            print('# Docker Start', flush=True)
            result = call_command('restart', app.name)
            print('Return', result, flush=True)

        return 0
