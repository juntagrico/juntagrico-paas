ADMIN_USERNAME = 'admin'
# passes the password to commands, so it does not appear in command lines or the process list
PASSWORD_ENV = 'ADMINCONSOLE_ADMIN_PASSWORD'

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
