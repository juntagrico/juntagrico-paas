from crontab import CronTab
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]
        comment = f'managed by admin console for {app_name}'

        cron = CronTab(user='juntagrico')
        cron.remove_all(comment=comment)
        depot_list = cron.new(
            command=f'docker exec {app_name} python -m manage generate_depot_list --future',
            comment=comment
        )
        depot_list.minute.on(50)
        depot_list.hour.on(23)
        reminder = cron.new(command=f'docker exec {app_name} python manage.py remind_members', comment=comment)
        reminder.minute.every(10)
        cron.write()
