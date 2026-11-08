from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import docker
from docker.errors import DockerException

from adminconsole.models import get_python_version_choices


class Command(BaseCommand):
    help = 'Pull the Docker images of supported python versions.'

    def handle(self, *args, **options):
        images = {
            f'python:{version}-alpine'
            for version in dict(get_python_version_choices())
            if version
        }
        images.add(f'python:{settings.DEFAULT_PYTHON_VERSION}-alpine')

        client = docker.from_env()
        failures = []

        try:
            for image in images:
                self.stdout.write(f'Pulling {image}...')
                try:
                    pulled = client.images.pull(image)
                    self.stdout.write(
                        self.style.SUCCESS(f'Pulled {pulled.tags or image}')
                    )
                except DockerException as exc:
                    failures.append(f'{image}: {exc}')
                    self.stderr.write(
                        self.style.ERROR(f'Failed to pull {image}: {exc}')
                    )
        finally:
            client.close()

        if failures:
            raise CommandError(
                f'Failed to pull {len(failures)} image(s): ' + '; '.join(failures)
            )
