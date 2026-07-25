import docker

from django.core.management.base import BaseCommand
from docker.errors import NotFound, APIError

from adminconsole.models import App


class Command(BaseCommand):
    """ collect installed package version
    """
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
        package += '=='

        for app in apps:
            version = None
            try:
                container = docker.from_env().containers.get(app.name)
            except NotFound:
                continue
            try:
                result = container.exec_run(['pip', 'freeze'])
            except APIError:
                continue
            for line in result.output.decode('utf-8').split('\n'):
                if line.startswith(package):
                    self.stdout.write(app.name + ': ' + line, ending='\n')
                    version = line[len(package):]
                    break
            if package == 'juntagrico==':
                app.juntagrico_version = version or ''
                app.save()
