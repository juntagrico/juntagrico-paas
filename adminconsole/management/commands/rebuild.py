import docker
from django.core.management import call_command

from django.core.management.base import BaseCommand
from docker.errors import BuildError

from adminconsole.models import App
from adminconsole.util.create_app import create_docker_file


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('python_version', nargs='?')
        parser.add_argument('--restart', action='store_true', help="Restart instance after rebuilding")
        parser.add_argument('--nocache', action='store_true', help="Build without using cache")

    # entry point used by manage.py
    def handle(self, *args, **options):
        app = App.objects.get(name=options['app_name'][0])
        python_version = options['python_version'] or app.python_version

        client = docker.from_env()

        build_args = {}
        if python_version:
            build_args['pythonversion'] = python_version

        create_docker_file(app)

        response = client.api.build(
            path=str(app.dir),
            tag=app.image_tag,
            buildargs=build_args,
            nocache=options.get('nocache'),
            decode=True
        )
        code = 0
        for line in response:
            error = line.get('error')
            stream = line.get('stream')
            if error:
                stream = error
                code = 1
            if stream:
                print(stream, flush=True)

        print(f'Return {code}', flush=True)
        if code == 1:
            return None

        if options.get('restart'):
            return call_command('restart', app.name)
        return 0
