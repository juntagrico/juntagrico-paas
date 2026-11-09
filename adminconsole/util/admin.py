from adminconsole.util.docker import _run_in_temp_container

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


def set_admin_password_in_container(app, password):
    """Set the admin password in a temporary container, returns exit code."""
    exit_code, _ = _run_in_temp_container(
        app,
        f'{app.name}-admin-password',
        ['python', '-m', 'manage', 'shell', '-c', SET_PASSWORD_SCRIPT],
        extra_env={PASSWORD_ENV: password},
    )
    return exit_code


def create_admin_user(app, password):
    """Create the admin user using a temporary container (idempotent).
    Returns True on success, False on failure.
    """
    # Try to create the admin user
    exit_code, _ = _run_in_temp_container(
        app,
        f'{app.name}-admin',
        ['python', '-m', 'manage', 'createadmin', '--noinput'],
        extra_env={
            'DJANGO_SUPERUSER_USERNAME': ADMIN_USERNAME,
            'DJANGO_SUPERUSER_PASSWORD': password,
            'DJANGO_SUPERUSER_EMAIL': 'admin@example.com',
        },
    )
    # If user already exists (exit code 1 for createsuperuser --noinput), set password instead
    if exit_code != 0:
        exit_code = set_admin_password_in_container(app, password)
    return exit_code == 0
