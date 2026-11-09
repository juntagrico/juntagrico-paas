from django.core.management import call_command
from django.core.management.base import BaseCommand

from adminconsole.models import App, AppEnv
from adminconsole.util.create_app import setup_domain
from adminconsole.util.docker import run_parallel_steps
from adminconsole.util.git import git_clone


class Command(BaseCommand):
    help = 'Set up a staging app: clone repo, create DB, clone data, set up domain, and redeploy.'

    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument(
            '--timeout',
            type=int,
            default=300,
            help='Timeout in seconds for database clone (default: 300)',
        )

    def handle(self, *args, **options):
        app = App.objects.get(name=options['app_name'][0])
        if not app.staging_of:
            print(f'{app} is not a staging app', flush=True)
            print('Return 1')
            return

        prod_app = app.staging_of

        # --- Step 1: Clone the repo ---
        print('# Git Clone', flush=True)
        errors = []
        if not git_clone(app, output=errors):
            for error in errors:
                print(error, flush=True)
            print('Git clone fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Step 2: Copy AppEnv from production ---
        print('# AppEnv kopieren', flush=True)
        if not hasattr(app, 'env'):
            prod_env = AppEnv.objects.get(app=prod_app)
            prod_env.pk = None
            prod_env.app = app
            prod_env.juntagrico_email_user = ''
            prod_env.juntagrico_email_password = ''
            prod_env.save()
        print('Return 0')

        # --- Step 3: Clone database from production (also creates the database) ---
        print('# Clone Database', flush=True)
        result = call_command(
            'clone_db', '--no-restart', '--timeout', options['timeout'], app.name
        )
        if result != 0:
            print('Return 1')
            return
        print('Return 0')

        # --- Step 4: Set up domain ---
        print('# Domain einrichten', flush=True)
        if not setup_domain(app):
            print('Domain einrichten fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Step 5: Docker rebuild ---
        print('# Docker Rebuild', flush=True)
        result = call_command('rebuild', app.name)
        if result != 0:
            print('Rebuild fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Step 6: Run migration, collectstatic, and restart in parallel ---
        exit_codes = run_parallel_steps(app, app.name)
        if any(code != 0 for code in exit_codes):
            print('Migration/collectstatic/restart fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Step 7: Collect version ---
        print('# Collect Version', flush=True)
        result = call_command('collect_version', app_name=app.name)
        if result != 0:
            print('Collect Version fehlgeschlagen (ignoriert)', flush=True)
        print('Return 0')

        # --- Mark installation as complete ---
        app.installation_pending = False
        app.save()
