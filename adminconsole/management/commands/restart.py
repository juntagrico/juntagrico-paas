import docker

from django.core.management.base import BaseCommand

from adminconsole.models import App
from adminconsole.util.network import apps_memory_limit, apps_network, ensure_apps_network


class Command(BaseCommand):
    """ v2 app command
    """
    def add_arguments(self, parser):
        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        app = App.objects.get(name=name)
        base_dir = app.dir

        client = docker.from_env()

        environment = list(app.env.get_lines())
        if app.isolated_network:
            # check the network before stopping the running container, so a problem does not take the app down
            network = ensure_apps_network(client)
            # the server is reachable at the gateway of the network; the last value of a variable wins
            gateway = apps_network()["gateway"]
            environment.append(f'JUNTAGRICO_DATABASE_HOST={gateway}')
            network_options = {
                'network': network.name,
                'ports': {f'{app.port}/tcp': ('127.0.0.1', app.port)},
                'command': ['gunicorn', '--forwarded-allow-ips', gateway, '--bind', f'0.0.0.0:{app.port}', '-t', '600', app.wsgi_path],
                'mem_limit': apps_memory_limit(),
            }
            print(f'network isolation: {network.name}', flush=True)
        else:
            network_options = {'network_mode': 'host'}

        try:
            container = client.containers.get(name)
            container.stop()
            container.remove()
        except:
            print('container not found or other error')

        labels = []
        if app.staging_of:
            labels.append('staging')

        volumes = {
            # needed to read staticfiles.json
            base_dir / 'static': {'bind': '/code/static/', 'mode': 'ro'},
            base_dir / 'media': {'bind': '/code/media/', 'mode': 'rw'},
            f'{name}-internal': {'bind': '/code/internal_files/', 'mode': 'rw'},
        }
        if app.version < 3:
            volumes[base_dir / 'code'] = {'bind': '/code/', 'mode': 'rw'}

        container = client.containers.run(
            image=app.image_tag,
            detach=True,
            environment=environment,
            name=name,
            labels=labels,
            **network_options,
            restart_policy={'Name': 'always'},
            volumes=volumes
        )
        print(container.status)
        print('Return 0', flush=True)
        return 0
