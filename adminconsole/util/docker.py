import docker

from docker.models.containers import ExecResult

from adminconsole.util.network import apps_memory_limit, apps_network, ensure_apps_network


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
            'command': ['gunicorn', '--forwarded-allow-ips', gateway, '--bind', f'0.0.0.0:{app.port}', '-t', '600', app.wsgi_path],
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
