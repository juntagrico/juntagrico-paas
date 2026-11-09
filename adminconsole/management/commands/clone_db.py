import subprocess  # nosec: B404

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from adminconsole.util.docker import _run_migration_in_temp_container
from adminconsole.models import App, AppEnv
from adminconsole.util.create_app import create_database


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument(
            '--no-restart', action='store_true', help="Don't restart container"
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=300,
            help='Timeout in seconds for pg_dump | psql (default: 300)',
        )

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
            app_env.juntagrico_email_password = ''  # nosec: B105
            app_env.save()
            app.env = app_env
        if not create_database(app.env, app.name, app.name, replace=True):
            print('Return 1')
            raise CommandError('Database creation failed')

        # copy tables from prod app
        print('# Clone Database', flush=True)
        target_user = app.env.juntagrico_database_user
        load = subprocess.Popen(  # nosec: B603, B607
            [
                'psql',
                '-h',
                'localhost',
                '-U',
                target_user,
                '--no-password',
                app.env.juntagrico_database_name,
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={'PGPASSWORD': app.env.juntagrico_database_password},
        )
        source_user = app.staging_of.env.juntagrico_database_user
        dump = subprocess.Popen(  # nosec: B603, B607
            [
                'pg_dump',
                '-h',
                'localhost',
                '-U',
                source_user,
                '--no-password',
                '--no-comments',
                '--no-owner',
                '--no-privileges',
                app.staging_of.env.juntagrico_database_name,
            ],
            stdout=load.stdin,
            env={'PGPASSWORD': app.staging_of.env.juntagrico_database_password},
        )
        timeout = options.get('timeout')
        try:
            dump.communicate(timeout=timeout)
            load.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            dump.kill()
            load.kill()
            dump.wait()
            load.wait()
            print(f'Database clone timed out after {timeout} seconds', flush=True)
            print('Return 1')
            raise CommandError(
                f'Database clone timed out after {timeout} seconds'
            ) from exc
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

        return
