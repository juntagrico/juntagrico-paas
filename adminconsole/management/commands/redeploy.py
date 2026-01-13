from datetime import datetime

import docker

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from adminconsole.models import App
from adminconsole.util.commands import log_after
from adminconsole.util.git import git_pull


class Command(BaseCommand):
    FORCE_REBUILD_SEP = '# force-rebuild '

    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('--upgrade', action='store_true', help="Force upgrade of requirements.txt")


    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)

        upgrade_nonce = timezone.now()
        if not options['upgrade']:
            # if we don't want to force an upgrade, store the current nonce to use again.
            # using the same nonce as in the last build will ensure that the right cache is used.
            try:
                with open(app.dir / 'code' / 'requirements.txt', 'r') as f:
                    upgrade_nonce = f.readlines()[-1].split(self.FORCE_REBUILD_SEP)[1]
            except FileNotFoundError:
                pass
            except IndexError:
                pass

        print('# Git Pull', flush=True)
        result = git_pull(app)
        print('Return', result, flush=True)

        # force cache invalidation
        # primitive method to enforce upgrade, because docker API doesn't seem to support --no-cache-filter option
        with open(app.dir / 'code' / 'requirements.txt', 'a') as f:
            f.write(f'\n{self.FORCE_REBUILD_SEP}{upgrade_nonce}')

        print('# Docker Rebuild', flush=True)
        result = call_command('rebuild', '--restart', app.name)
        if result != 0:
            return

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
