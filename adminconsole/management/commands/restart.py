import docker

from django.core.management.base import BaseCommand

from adminconsole.models import App


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)
        base_dir = app.dir

        client = docker.from_env()

        try:
            container = client.containers.get(name)
            container.stop()
            container.remove()
        except:
            print('container not found or other error')

        container = client.containers.run(
            image=name + ':latest',
            detach=True,
            environment=list(app.env.get_lines()),
            name=name,
            network_mode='host',
            restart_policy={'Name': 'always'},
            volumes={
                base_dir / 'code': {'bind': '/code/', 'mode': 'rw'},
                base_dir / 'static': {'bind': '/code/static/', 'mode': 'rw'},
                base_dir / 'media': {'bind': '/code/media/', 'mode': 'rw'},
            }
        )
        print(container.status)
