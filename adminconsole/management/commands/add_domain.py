import subprocess  # nosec: B404
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import get_template

from adminconsole.models import Domain


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('domains', nargs='*')

    # entry point used by manage.py
    def handle(self, *args, **options):
        for domain in Domain.objects.filter(name__in=options['domains']):
            config_path = Path(settings.NGINX_SITES_DIR) / domain.name
            with open(config_path, 'w') as domain_file:
                domain_file.write(
                    get_template('infra/domain.txt').render({
                        'name': domain.app.name,
                        'port': domain.app.port,
                        'domain': domain.name,
                    })
                )

            # Install SSL certificate (skipped in Docker — HTTPS is handled externally)
            if not settings.DOCKERIZED:
                proc = subprocess.run(  # nosec: B603
                    ['sudo', '/usr/local/sbin/juntagrico-certbot', domain.name],
                    stdout=subprocess.PIPE,
                )
                print(str(proc.stdout))
                print('Return', proc.returncode)
            else:
                print('Return 0')
