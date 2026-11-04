from django.core.management.base import BaseCommand

from adminconsole.models import App
from adminconsole.util.docker import create_container, stop_container


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)

        stop_container(name)
        container = create_container(app)
        print(container.status)
        print('Return 0', flush=True)
        return 0
