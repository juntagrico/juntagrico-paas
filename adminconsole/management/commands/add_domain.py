from django.core.management.base import BaseCommand

from adminconsole.models import Domain
from adminconsole.util.create_app import request_ssl_certificate, write_domain_config


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('domains', nargs='*')

    # entry point used by manage.py
    def handle(self, *args, **options):
        for domain in Domain.objects.filter(name__in=options['domains']):
            write_domain_config(domain.app, domain.name)

            # install ssl, the wrapper is the only command the user may run with sudo
            request_ssl_certificate(domain.name)
