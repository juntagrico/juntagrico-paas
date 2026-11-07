import subprocess  # nosec: B404

from django.core.management.base import BaseCommand
from django.template.loader import get_template

from adminconsole.models import Domain


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('domains', nargs='*')

    # entry point used by manage.py
    def handle(self, *args, **options):
        for domain in Domain.objects.filter(name__in=options['domains']):
            with open('/var/django/domains/' + domain.name, 'w') as domain_file:
                domain_file.write(
                    get_template('infra/domain.txt').render({
                        'name': domain.app.name,
                        'port': domain.app.port,
                        'domain': domain.name,
                    })
                )

            # install ssl, the wrapper is the only command the user may run with sudo
            proc = subprocess.run(  # nosec: B603, B607
                ['sudo', '/usr/local/sbin/juntagrico-certbot', domain.name],
                stdout=subprocess.PIPE,
            )
            print(str(proc.stdout))

            print('Return', proc.returncode)
