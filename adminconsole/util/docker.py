import docker

from docker.errors import NotFound, ContainerError
from docker.models.containers import ExecResult

from adminconsole.util.network import apps_memory_limit, apps_network, ensure_apps_network


def _run_migration_in_temp_container(app, name):
    """Run Django migrations in a temporary container with the latest environment."""
    client = docker.from_env()
    volumes = {}
    if app.version < 3:
        volumes[app.dir / 'code'] = {'bind': '/code/', 'mode': 'ro'}
    # Match the network mode of the running container so the temp container can reach the database
    if app.isolated_network:
        network = ensure_apps_network(client)
        network_kwargs = {'network': network.name}
    else:
        network_kwargs = {'network_mode': 'host'}
    try:
        output = client.containers.run(
            image=app.image_tag,
            environment=list(app.env.get_lines()),
            name=name + '-migrate',
            labels=['migrate'],
            volumes=volumes,
            command='python -m manage migrate --noinput',
            remove=True,
            stdout=True,
            stderr=True,
            **network_kwargs,
        )
        print(output.decode("utf-8", errors="replace"), end="", flush=True)
        print('Return 0', flush=True)
        return 0
    except ContainerError as exc:
        if exc.stderr:
            print(exc.stderr.decode("utf-8", errors="replace"))
        print('Return', exc.exit_status, flush=True)
        return exc.exit_status


def exec_run(container, cmd, stdout=True, stderr=True, stdin=False, tty=False,
             privileged=False, user='', detach=False, stream=False,
             socket=False, environment=None, workdir=None, demux=False):
    """
    workaround to get result code when using exec_run with stream=true
    """
    resp = container.client.api.exec_create(
        container.id, cmd, stdout=stdout, stderr=stderr, stdin=stdin, tty=tty,
        privileged=privileged, user=user, environment=environment,
        workdir=workdir,
    )
    exec_output = container.client.api.exec_start(
        resp['Id'], detach=detach, tty=tty, stream=stream, socket=socket,
        demux=demux
    )

    def exit_code():
        return container.client.api.exec_inspect(resp['Id']).get('ExitCode')

    if socket or stream:
        return ExecResult(exit_code, exec_output)

    return ExecResult(
        container.client.api.exec_inspect(resp['Id'])['ExitCode'],
        exec_output
    )


def stop_container(name):
    """Stop and remove a Docker container by name. Silently ignores NotFound."""
    client = docker.from_env()
    try:
        container = client.containers.get(name)
        container.stop()
        container.remove()
    except NotFound:
        pass


def get_container_statuses(app_names):
    """
    Efficiently get the running status of multiple containers in a single Docker API call.
    Returns a dict mapping container names to booleans (True if running).
    """
    client = docker.from_env()
    all_containers = client.containers.list(all=True)
    statuses = {}
    for container in all_containers:
        name = container.name
        if name in app_names:
            statuses[name] = container.status in ('running', 'created', 'restarting')
    return statuses


def create_container(app):
    """Create and start a Docker container for the given app."""
    client = docker.from_env()
    name = app.name
    base_dir = app.dir

    environment = list(app.env.get_lines())
    if app.isolated_network:
        network = ensure_apps_network(client)
        gateway = apps_network()["gateway"]
        environment.append(f'JUNTAGRICO_DATABASE_HOST={gateway}')
        network_options = {
            'network': network.name,
            'ports': {f'{app.port}/tcp': ('127.0.0.1', app.port)},
            'command': ['gunicorn', '--no-control-socket', '--forwarded-allow-ips', gateway] +
                       ['--bind', f'0.0.0.0:{app.port}', '-t', '600', app.wsgi_path],
            'mem_limit': apps_memory_limit(),
        }
    else:
        network_options = {'network_mode': 'host'}

    labels = []
    if app.staging_of:
        labels.append('staging')

    volumes = {
        base_dir / 'static': {'bind': '/code/static/', 'mode': 'ro'},
        base_dir / 'media': {'bind': '/code/media/', 'mode': 'rw'},
        f'{name}-internal': {'bind': '/code/internal_files/', 'mode': 'rw'},
    }
    if app.version < 3:
        volumes[base_dir / 'code'] = {'bind': '/code/', 'mode': 'rw'}

    return client.containers.run(
        image=app.image_tag,
        detach=True,
        environment=environment,
        name=name,
        labels=labels,
        **network_options,
        restart_policy={'Name': 'always'},
        volumes=volumes
    )
