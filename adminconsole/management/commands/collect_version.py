import docker

from django.core.management.base import BaseCommand
from docker.errors import NotFound, APIError

from adminconsole.models import App


class Command(BaseCommand):
    """Collect installed package version using importlib.metadata (no pip required)."""

    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs='?')
        parser.add_argument('package', nargs='?', default='juntagrico')

    # entry point used by manage.py
    def handle(self, app_name=None, package=None, *args, **options):
        if app_name is None:
            apps = App.objects.all()
        else:
            apps = App.objects.filter(name=app_name)
        package = package or 'juntagrico'

        return_code = 'package not found'
        for app in apps:
            version = None
            try:
                container = docker.from_env().containers.get(app.name)
            except NotFound:
                continue
            try:
                result = container.exec_run(
                    ['python', '-c',
                     f'import importlib.metadata; print(importlib.metadata.version("{package}"))']
                )
            except APIError:
                continue
            output = result.output.decode('utf-8').strip()
            if result.exit_code == 0:
                self.stdout.write(f'{app.name}: {package}=={output}', ending='\n')
                version = output
                return_code = '0'
            else:
                self.stdout.write(f'{app.name}: {package} not installed', ending='\n')
            if package == 'juntagrico':
                app.juntagrico_version = version or ''
                app.save()
        return return_code