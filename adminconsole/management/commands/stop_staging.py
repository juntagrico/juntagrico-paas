import docker

from django.core.management.base import BaseCommand
from django.utils import timezone
from docker.errors import NotFound

from adminconsole.models import App


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Don't actually stop container")

    # entry point used by manage.py
    def handle(self, *args, **options):
        client = docker.from_env()
        dry_run = options.get('dry_run')
        for app in App.objects.filter(run_until__isnull=False, run_until__lte=timezone.now()):
            if dry_run:
                print(f'Would stop {app}')
            else:
                try:
                    client.containers.get(app.name).stop()
                except NotFound:
                    continue
                print(f'stopped {app}')
