from datetime import datetime

import docker

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from adminconsole.models import App
from adminconsole.util.commands import log_after
from adminconsole.util.git import git_pull


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('--upgrade', action='store_true', help="Force upgrade of requirements.txt")


    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)

        print('# Git Pull', flush=True)
        result = git_pull(app)
        print('Return', result, flush=True)

        args=[]
        if options['upgrade']:
            # ignore entire cache, because docker API doesn't seem to support --no-cache-filter option
            args.append('--nocache')

        print('# Docker Rebuild', flush=True)
        call_command('rebuild', '--restart', *args, app.name)

        container = docker.from_env().containers.get(name)

        print('# Django Migrate', flush=True)
        cmd = ['python', '-m', 'manage', 'migrate']
        result = container.exec_run(cmd)
        print(result[1])
        print('Return', result[0], flush=True)

        print('# Django Collectstatic', flush=True)
        cmd = ['python', '-m', 'manage', 'collectstatic', '--noinput', '-c']
        result = container.exec_run(cmd)
        print(result[1])
        print('Return', result[0], flush=True)

        print('# Docker Restart', flush=True)
        start = datetime.now()
        container.restart()
        print(log_after(container, since=start))
        print('Return 0', flush=True)
