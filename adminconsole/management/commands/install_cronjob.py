from crontab import CronTab
from django.conf import settings
from django.core.management.base import BaseCommand

from adminconsole.models import App, get_cronjob_definition


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        app_name = options['app_name'][0]
        try:
            app = App.objects.get(name=app_name)

            comment = f'managed by admin console for {app_name}'

            cron = CronTab(user='juntagrico')
            cron.remove_all(comment=comment)

            for app_cronjob in app.cronjobs.all():
                definition = get_cronjob_definition(app_cronjob.cronjob_id)
                if definition is None:
                    continue

                job = cron.new(
                    command=f'docker exec {app_name} python -m manage {definition["command"]}',
                    comment=comment
                )

                timing = definition.get('timing', 'fixed')

                if timing == 'fixed':
                    # Fully defined in settings
                    minute_val = definition.get('minute')
                    hour_val = definition.get('hour')
                    if minute_val == '*':
                        job.minute.every(1)
                    elif isinstance(minute_val, int):
                        job.minute.on(minute_val)
                    elif isinstance(minute_val, str) and '/' in minute_val:
                        # e.g. '*/10'
                        interval = int(minute_val.split('/')[1])
                        job.minute.every(interval)
                    else:
                        job.minute.on(int(minute_val))

                    if hour_val == '*':
                        job.hour.every(1)
                    elif isinstance(hour_val, int):
                        job.hour.on(hour_val)

                elif timing == 'hourly':
                    # Every hour at the specified minute
                    minute = app_cronjob.minute if app_cronjob.minute is not None else app.port % 60
                    job.minute.on(minute)
                    job.hour.every(1)

                elif timing == 'daily':
                    # Once a day at the specified hour and minute
                    hour = app_cronjob.hour if app_cronjob.hour is not None else definition.get('default_hour', 23)
                    minute = app_cronjob.minute if app_cronjob.minute is not None else definition.get('default_minute', 0)
                    job.hour.on(hour)
                    job.minute.on(minute)

            cron.write()
            print('Return 0')
        except Exception as e:
            print(str(e))
            print('Return 1')
