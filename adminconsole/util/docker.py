import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import docker

from docker.errors import NotFound, ContainerError
from docker.models.containers import ExecResult

from adminconsole.util.network import apps_memory_limit, apps_network, ensure_apps_network


def get_container_env_and_network(app, client):
    """
    Return (environment, network_kwargs) for a container matching the app's network configuration.
    For isolated networks, the environment includes JUNTAGRICO_DATABASE_HOST pointing to the gateway,
    and network_kwargs connects to the apps bridge network.
    For non-isolated apps, network_kwargs uses host mode.
    """
    environment = list(app.env.get_lines())
    if app.isolated_network:
        network = ensure_apps_network(client)
        gateway = apps_network()["gateway"]
        environment.append(f'JUNTAGRICO_DATABASE_HOST={gateway}')
        network_kwargs = {'network': network.name}
    else:
        network_kwargs = {'network_mode': 'host'}
    return environment, network_kwargs


def _run_in_temp_container(app, name, command, volumes=None, user=None):
    """
    Run a command in a temporary container with the latest environment.
    Returns (exit_code, output_bytes, error_bytes).
    """
    client = docker.from_env()
    if volumes is None:
        volumes = {}
    if app.version < 3:
        volumes.setdefault(app.dir / 'code', {'bind': '/code/', 'mode': 'ro'})
    environment, network_kwargs = get_container_env_and_network(app, client)
    kwargs = {
        'image': app.image_tag,
        'environment': environment,
        'name': name,
        'volumes': volumes,
        'command': command,
        'remove': True,
        'stdout': True,
        'stderr': True,
    }
    if user:
        kwargs['user'] = user
    kwargs.update(network_kwargs)
    try:
        output = client.containers.run(**kwargs)
        return 0, output, b''
    except ContainerError as exc:
        return exc.exit_status, exc.stdout or b'', exc.stderr or b''


def _run_migration_in_temp_container(app, name):
    """Run Django migrations in a temporary container with the latest environment."""
    volumes = {}
    exit_code, output, stderr = _run_in_temp_container(
        app, name + '-migrate', 'python -m manage migrate --noinput', volumes=volumes
    )
    if output:
        print(output.decode("utf-8", errors="replace"), end="", flush=True)
    if stderr:
        print(stderr.decode("utf-8", errors="replace"), end="", flush=True)
    print(f'Return {exit_code}', flush=True)
    return exit_code


def _run_collectstatic_in_temp_container(app, name):
    """Run collectstatic in a temporary container with the latest environment."""
    static_dir = app.dir / 'static'
    static_stat = os.stat(static_dir)
    volumes = {static_dir: {'bind': '/code/static/', 'mode': 'rw'}}
    exit_code, output, stderr = _run_in_temp_container(
        app, name + '-collectstatic',
        'python -m manage collectstatic --noinput -c',
        volumes=volumes,
        user=f'{static_stat.st_uid}:{static_stat.st_gid}',
    )
    if output:
        print(output.decode("utf-8", errors="replace"), end="", flush=True)
    if stderr:
        print(stderr.decode("utf-8", errors="replace"), end="", flush=True)
    print(f'Return {exit_code}', flush=True)
    return exit_code


def run_parallel_steps(app, name):
    """
    Run migration, collectstatic, and restart in parallel.
    Each step's output is buffered and printed in a fixed order after all complete.
    Returns a list of exit codes for each step.
    """
    from django.core.management import call_command

    output_buffer = {}
    lock = Lock()

    def task_migration():
        code, out, err = _run_in_temp_container(
            app, name + '-migrate', 'python -m manage migrate --noinput', volumes={}
        )
        with lock:
            output_buffer['migrate'] = (code, out, err)

    def task_collectstatic():
        static_dir = app.dir / 'static'
        static_stat = os.stat(static_dir)
        volumes = {static_dir: {'bind': '/code/static/', 'mode': 'rw'}}
        user = f'{static_stat.st_uid}:{static_stat.st_gid}'
        code, out, err = _run_in_temp_container(
            app, name + '-collectstatic',
            'python -m manage collectstatic --noinput -c',
            volumes=volumes,
            user=user,
        )
        with lock:
            output_buffer['collectstatic'] = (code, out, err)

    def task_restart():
        code = call_command('restart', name)
        with lock:
            output_buffer['restart'] = (code, b'', b'')

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(task_migration),
            executor.submit(task_collectstatic),
            executor.submit(task_restart),
        ]
        for future in as_completed(futures):
            future.result()

    # Print output in fixed order
    order = [
        ('migrate', '# Django Migrate'),
        ('collectstatic', '# Django Collectstatic'),
        ('restart', '# Docker Start'),
    ]
    exit_codes = []
    for key, header in order:
        print(header, flush=True)
        code, out, err = output_buffer.get(key, (0, b'', b''))
        if out:
            print(out.decode("utf-8", errors="replace"), end="", flush=True)
        if err:
            print(err.decode("utf-8", errors="replace"), end="", flush=True)
        print(f'Return {code}', flush=True)
        exit_codes.append(code)

    return exit_codes


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

    environment, network_options = get_container_env_and_network(app, client)
    if app.isolated_network:
        gateway = apps_network()["gateway"]
        network_options['ports'] = {f'{app.port}/tcp': ('127.0.0.1', app.port)}
        network_options['command'] = (
            ['gunicorn', '--no-control-socket', '--forwarded-allow-ips', gateway]
            + ['--bind', f'0.0.0.0:{app.port}', '-t', '600', app.wsgi_path]
        )
        network_options['mem_limit'] = apps_memory_limit()

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
