import subprocess

import docker
from django.core.management import call_command

from django.core.management.base import BaseCommand

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

        if app.version >= 3:
            build_args['appuser'] = app.name
            build_args['appuid'] = 10000 + app.port
            if '@' in app.git_clone_url:
                build_args['git_repo'], build_args['git_ref'] = app.git_clone_url.split('@')
            else:
                build_args['git_repo'] = app.git_clone_url

            cmd = [
                'docker',
                'buildx',
                'build',
                '--no-cache-filter',
                'app',
                '--tag',
                app.image_tag,
            ]

            if options.get('nocache', False):
                cmd.append('--no-cache')

            for key, value in build_args.items():
                cmd.extend(['--build-arg', f'{key}={value}'])

            # Make the built image available to the local Docker daemon.
            cmd.append('--load')
            cmd.append(str(app.dir))

            result = subprocess.run(cmd, check=False)
            code = result.returncode

            print(f'Return {code}', flush=True)
            if code != 0:
                return None
        else:
            response = client.api.build(
                path=str(app.dir),
                tag=app.image_tag,
                buildargs=build_args,
                nocache=options.get('nocache', False),
                decode=True,
                rm=True,
            )
            code = 0
            for line in response:
                error = line.get('error')
                stream = line.get('stream')
                if error:
                    stream = error
                    code = 1
                if stream:
                    print(stream, end='', flush=True)
    
            print(f'Return {code}', flush=True)
            if code == 1:
                return None

        if options.get('restart'):
            return call_command('restart', app.name)
        return 0
