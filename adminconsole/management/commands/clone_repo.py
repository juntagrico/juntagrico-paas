from django.core.management.base import BaseCommand

from adminconsole.models import App
from adminconsole.util.git import git_clone


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    def handle(self, *args, **options):
        app = App.objects.get(name=options['app_name'][0])

        errors = []
        git_clone(app, output=errors)

        for error in errors:
            print(error)
