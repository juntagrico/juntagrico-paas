import docker

ADMIN_USERNAME = 'admin'
# passes the password to commands, so it does not appear in command lines or the process list
PASSWORD_ENV = 'ADMINCONSOLE_ADMIN_PASSWORD'  # nosec: B105

SET_PASSWORD_SCRIPT = f"""
import os
from django.contrib.auth import get_user_model
user = get_user_model().objects.get(username={ADMIN_USERNAME!r})
user.set_password(os.environ[{PASSWORD_ENV!r}])
user.save()
"""


def set_admin_password(container, password):
    """sets the password of the admin user of the app running in the container, returns the exec result"""
    return container.exec_run(
        ['python', '-m', 'manage', 'shell', '-c', SET_PASSWORD_SCRIPT],
        environment={PASSWORD_ENV: password},
    )


def create_admin_user(app_name, password):
    """Create the admin user in the app container (idempotent).
    Returns True on success, False on failure.
    """
    try:
        container = docker.from_env().containers.get(app_name)
    except docker.errors.NotFound:
        return False

    # Try to create the admin user; if it already exists, just set the password
    result = container.exec_run(
        ['python', '-m', 'manage', 'createadmin', '--noinput'],
        environment={
            'DJANGO_SUPERUSER_USERNAME': ADMIN_USERNAME,
            'DJANGO_SUPERUSER_PASSWORD': password,
            'DJANGO_SUPERUSER_EMAIL': 'admin@example.com',
        },
    )
    # If user already exists (exit code 1 for createsuperuser --noinput), set password instead
    if result.exit_code != 0:
        result = set_admin_password(container, password)
    return result.exit_code == 0
