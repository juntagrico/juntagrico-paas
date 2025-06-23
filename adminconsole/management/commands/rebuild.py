import docker

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)
        parser.add_argument('python_version', nargs='?', default='3.9')

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        python_version = options['python_version']
        base_dir = '/var/django/projects/'+name

        client = docker.from_env()

        result = client.images.build(path=base_dir, tag=name+':latest', buildargs={'pythonversion': python_version})
        print(*result[1], sep="\n")
        return 0
