import subprocess
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]
        proc = subprocess.run(
            [
                '(crontab -l 2>/dev/null; '
                'echo "59 23 * * * docker exec ' + app_name + ' python -m manage generate_depot_list") '
                '| crontab -'
            ],
            stdout=subprocess.PIPE
        )
        print(str(proc.stdout))
