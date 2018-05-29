import subprocess

from django.core.management.base import BaseCommand
from django.template.loader import get_template


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)
        parser.add_argument('port', nargs=1)
        parser.add_argument('domain', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        port = options['port'][0]
        domain = options['domain'][0]

        rdir = '/root'

        template = get_template('env/domain.txt')
        d = {
            'name': name,
            'port': port,
            'domain': domain,
        }
        content = template.render(d)

        with open('/etc/nginx/sites-available'+domain, "w") as domain_file:
            domain_file.write(content)

        proc = subprocess.run(['ln', '-s', '/etc/nginx/sites-available/'+domain, '/etc/nginx/sites-enabled'], stdout = subprocess.PIPE)
        print(str(proc.stdout))
        proc = subprocess.run(['./certbot-auto', '--nginx', '--redirect', '--keep', '-n', '-d', domain], stdout = subprocess.PIPE, cwd=rdir)
        print(str(proc.stdout))
