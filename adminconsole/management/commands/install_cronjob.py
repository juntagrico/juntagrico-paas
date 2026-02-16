from crontab import CronTab
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]

        new_command = 'docker exec ' + app_name + ' python -m manage generate_depot_list'
        cron = CronTab(user='root')
        job = cron.new(command=new_command)
        job.minute.on(59)
        job.hour.on(23)
        cron.write()

        print(new_command)
