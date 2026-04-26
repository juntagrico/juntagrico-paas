import subprocess

from django.core.management.base import BaseCommand
from django.template.loader import get_template

from adminconsole.models import Domain


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('domains', nargs='*')

    # entry point used by manage.py
    def handle(self, *args, **options):
        for domain in Domain.objects.filter(name__in=options['domains']):
            with open('/etc/nginx/sites-available/' + domain.name, "w") as domain_file:
                domain_file.write(get_template('infra/domain.txt').render({
                    'name': domain.app.name,
                    'port': domain.app.port,
                    'domain': domain.name,
                }))

            # activate site
            proc = subprocess.run(['ln', '-sf', '/etc/nginx/sites-available/' + domain.name, '/etc/nginx/sites-enabled'],
                                  stdout=subprocess.PIPE)
            print(str(proc.stdout))
            # install ssl
            proc = subprocess.run(['certbot', '--nginx', '--redirect', '--keep', '-n', '-d', domain.name],
                                  stdout=subprocess.PIPE)
            print(str(proc.stdout))
