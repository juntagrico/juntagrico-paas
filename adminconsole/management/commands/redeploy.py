from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from adminconsole.models import App
from adminconsole.util.docker import run_parallel_steps
from adminconsole.util.git import git_pull


class Command(BaseCommand):
    FORCE_REBUILD_SEP = '# force-rebuild '

    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('--upgrade', action='store_true', help="Force upgrade of requirements.txt")
        parser.add_argument('--copy-data', action='store_true', help="Copy data from production to staging")


    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)

        if app.version < 3:
            upgrade_nonce = timezone.now()
            if not options['upgrade']:
                # if we don't want to force an upgrade, store the current nonce to use again.
                # using the same nonce as in the last build will ensure that the right cache is used.
                try:
                    with open(app.code_dir / 'requirements.txt', 'r') as f:
                        upgrade_nonce = f.readlines()[-1].split(self.FORCE_REBUILD_SEP)[1]
                except FileNotFoundError:
                    pass
                except IndexError:
                    pass

            print('# Git Pull', flush=True)
            result = git_pull(app)
            print('Return', result, flush=True)
            if result != 0:
                return

            # force cache invalidation
            # primitive method to enforce upgrade, because docker API doesn't seem to support --no-cache-filter option
            with open(app.code_dir / 'requirements.txt', 'a') as f:
                f.write('\nsvglib<1.6.0')  # force fix. 1.6. requires cairo
                f.write(f'\n{self.FORCE_REBUILD_SEP}{upgrade_nonce}')

        print('# Docker Rebuild', flush=True)
        result = call_command('rebuild', app.name)
        if result != 0:
            return

        if options.get('copy_data'):
            print('# Clone Database', flush=True)
            result = call_command('clone_db', '--no-restart', app.name)
            if result != 0:
                return

        # Run migration, collectstatic, and restart in parallel
        exit_codes = run_parallel_steps(app, name)
        if any(code != 0 for code in exit_codes):
            return

        # update juntagrico version register (needs running container)
        print('# Collect Version', flush=True)
        result = call_command('collect_version', app_name=app.name)
        print('Return', result, flush=True)
