import os

from django.core.management import call_command
from django.core.management.base import BaseCommand

from adminconsole.models import App, AppEnv
from adminconsole.util.admin import PASSWORD_ENV, create_admin_user
from adminconsole.util.create_app import (
    create_database,
    create_default_cronjobs,
    setup_domain,
)
from adminconsole.util.docker import run_parallel_steps
from adminconsole.management.commands.install_cronjob import install_cronjobs_for_app


class Command(BaseCommand):
    help = 'Run initial setup steps for a new app: init db, init domain, redeploy, init cronjobs, create admin.'

    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)

        # --- Check admin password env var first ---
        password = os.environ.get(PASSWORD_ENV)
        if not password:
            print('Admin Passwort nicht gesetzt', flush=True)
            print('Return 1')
            return

        # --- Step 1: Init DB (idempotent) ---
        print('# Datenbank erstellen', flush=True)
        app_env = AppEnv.objects.get_or_create(app=app)[0]
        if not create_database(app_env, name, name):
            print('Return 1')
            return
        print('Datenbank erstellt', flush=True)
        print('Return 0')

        # --- Step 2: Redeploy (idempotent) ---
        print('# Docker Rebuild', flush=True)
        result = call_command('rebuild', app.name)
        if result != 0:
            print('Rebuild fehlgeschlagen', flush=True)
            print('Return 1')
            return

        # --- Step 3: Init Domain (idempotent) - after rebuild, before parallel steps ---
        print('# Domain einrichten', flush=True)
        if not setup_domain(app):
            print('Domain einrichten fehlgeschlagen', flush=True)
            print('Return 1')
            return
        else:
            print('Return 0')

        # --- Parallel steps (migration, collectstatic, restart) ---
        exit_codes = run_parallel_steps(app, name)
        if any(code != 0 for code in exit_codes):
            print('Migration/collectstatic/restart fehlgeschlagen', flush=True)
            print('Return 1')
            return

        # --- Step 4: Init Cronjobs (idempotent) ---
        print('# Cronjob einrichten', flush=True)
        create_default_cronjobs(app)
        if not install_cronjobs_for_app(app):
            print('Cronjob einrichten fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Step 5: Create admin user (idempotent) ---
        print('# Admin erstellen', flush=True)
        if not create_admin_user(app.name, password):
            print('Admin erstellen fehlgeschlagen', flush=True)
            print('Return 1')
            return
        print('Return 0')

        # --- Collect version at the very end (non-fatal) ---
        print('# Collect Version', flush=True)
        result = call_command('collect_version', app_name=app.name)
        if result != 0:
            print('Collect Version fehlgeschlagen (ignoriert)', flush=True)
        print('Return 0')
