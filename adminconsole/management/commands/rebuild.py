import subprocess  # nosec: B404

import docker
from django.conf import settings
from django.core.management import call_command

from django.core.management.base import BaseCommand
from django.template.loader import get_template

from adminconsole.models import App
from adminconsole.util.create_app import create_docker_file, ensure_dirs
from adminconsole.util.docker import ensure_dir_permissions


class Command(BaseCommand):
    """v2 app command"""

    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('python_version', nargs='?')
        parser.add_argument(
            '--restart', action='store_true', help='Restart instance after rebuilding'
        )
        parser.add_argument(
            '--nocache', action='store_true', help='Build without using cache'
        )
        parser.add_argument(
            '--target',
            type=str,
            help='Build stage target (requires app version 3; only builds an image tagged with the stage name, never restarts)',
        )

    # entry point used by manage.py
    def handle(self, *args, **options):
        app = App.objects.get(name=options['app_name'][0])
        python_version = options['python_version'] or app.python_version
        target = options.get('target', '')

        if target and app.version < 3:
            print('Error: --target requires app version 3 or higher.')
            print('Return 1', flush=True)
            return None

        client = docker.from_env()

        build_args = {}
        if python_version:
            build_args['pythonversion'] = python_version

        if not target:
            if not ensure_dirs(app):
                print('Error: failed create dirs.')
                print('Return 42', flush=True)
                return None

        if app.version >= 3:
            build_args['appuser'] = app.name
            build_args['appuid'] = app.uid
            build_args['git_repo'] = app.git_clone_url
            if app.git_branch:
                build_args['git_ref'] = app.git_branch

            image_tag = f'{app.image_tag}-{target}' if target else app.image_tag
            cmd = ['docker', 'buildx', 'build'] + ['--tag', image_tag]

            if target:
                cmd.extend(['--target', target])

            if options.get('nocache', False):
                cmd.append('--no-cache')
            else:
                # always pull latest changes from branch
                cmd.extend(['--no-cache-filter', 'fetcher'])

            for key, value in build_args.items():
                cmd.extend(['--build-arg', f'{key}={value}'])

            # Make the built image available to the local Docker daemon.
            cmd.append('--load')
            cmd.append('-')

            result = subprocess.run(  # nosec: B603
                cmd,
                input=get_template(f'infra/v{app.version}/Dockerfile').render({
                    'app': app,
                    'default_python_version': settings.DEFAULT_PYTHON_VERSION,
                }),
                text=True,
                check=False,
            )
            code = result.returncode

            print(f'Return {code}', flush=True)
            if code != 0:
                return None

        else:
            create_docker_file(app)

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

        if not target:
            if err_code := ensure_dir_permissions(app):
                print('Error: failed set up dirs.')
                print(f'Return {err_code}', flush=True)
                return None

            if options.get('restart'):
                return call_command('restart', app.name)
        return 0
