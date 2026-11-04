from django.core.management.base import BaseCommand
from django.utils import timezone

from adminconsole.models import App
from adminconsole.util.docker import stop_container


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Don't actually stop container")

    # entry point used by manage.py
    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        for app in App.objects.filter(run_until__isnull=False, run_until__lte=timezone.now()):
            if dry_run:
                print(f'Would stop {app}')
            else:
                stop_container(app.name)
                print(f'stopped {app}')
