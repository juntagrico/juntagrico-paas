import os
from concurrent.futures import ThreadPoolExecutor

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


def _do_restart(app, name):
    """Stop and recreate the container; returns (exit_code, stdout_bytes, stderr_bytes)."""
    try:
        stop_container(name)
        container = create_container(app)
        status = container.status
        return 0, f'{status}\n'.encode(), b''
    except Exception as exc:
        return 1, b'', str(exc).encode()


def run_parallel_steps(app, name):
    """
    Run migration, collectstatic, and restart in parallel.
    All three work tasks start immediately via Futures. The main thread prints
    each step's header right away, then waits for that Future to print its output.
    This ensures headers appear before their work completes, while output blocks
    remain sequential: migration → collectstatic → restart.
    Returns a list of exit codes for each step.
    """

    def _print_output(code, out, err):
        """Print buffered stdout/stderr and return code."""
        if out:
            print(out.decode("utf-8", errors="replace"), end="", flush=True)
        if err:
            print(err.decode("utf-8", errors="replace"), end="", flush=True)
        print(f'Return {code}', flush=True)

    # Prepare collectstatic arguments
    static_dir = app.dir / 'static'
    static_dir.mkdir(parents=True, exist_ok=True)
    static_stat = os.stat(static_dir)
    collectstatic_volumes = {static_dir: {'bind': '/code/static/', 'mode': 'rw'}}
    collectstatic_user = f'{static_stat.st_uid}:{static_stat.st_gid}'

    # Submit all work as Futures — they start immediately
    with ThreadPoolExecutor(max_workers=3) as executor:
        migrate_future = executor.submit(
            _run_in_temp_container, app, name + '-migrate',
            'python -m manage migrate --noinput', volumes={}
        )
        collectstatic_future = executor.submit(
            _run_in_temp_container, app, name + '-collectstatic',
            'python -m manage collectstatic --noinput -c',
            volumes=collectstatic_volumes, user=collectstatic_user,
        )
        restart_future = executor.submit(_do_restart, app, name)

        # Print migration block: header immediately, output when ready
        print('# Django Migrate', flush=True)
        code, out, err = migrate_future.result()
        _print_output(code, out, err)
        migrate_exit = code

        # Print collectstatic block: header immediately, output when ready
        print('# Django Collectstatic', flush=True)
        code, out, err = collectstatic_future.result()
        _print_output(code, out, err)
        collectstatic_exit = code

        # Print restart block: header immediately, output when ready
        print('# Docker Start', flush=True)
        code, out, err = restart_future.result()
        _print_output(code, out, err)
        restart_exit = code

    return [migrate_exit, collectstatic_exit, restart_exit]


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
