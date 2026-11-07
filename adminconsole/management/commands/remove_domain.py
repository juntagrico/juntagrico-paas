from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('domain', nargs='*')

    # entry point used by manage.py
    def handle(self, *args, **options):
        for domain in options['domain']:
            (Path(settings.NGINX_SITES_DIR) / domain).unlink(missing_ok=True)
