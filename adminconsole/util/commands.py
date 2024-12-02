from time import sleep


def log_after(container, target='running', since=None, timeout=20):
    """ waits until a docker container reached status `target`, then returns the logs
    :param container: a docker container
    :param target: a docker container status, e.g. 'running', 'exited'
    :param since: datetime since when the logs should be printed
    :param timeout: timeout in seconds
    """
    elapsed_time = 0
    interval = 1
    while container.status != target and elapsed_time < timeout:
        sleep(interval)
        elapsed_time += interval
        container.reload()
    return container.logs(since=since)
