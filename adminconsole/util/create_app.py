from django.conf import settings
from django.db import connection
from django.template.loader import get_template

from adminconsole.models import App
from adminconsole.util import generate_password


def find_port():
    ports = App.objects.all().values_list('port', flat=True)
    port = 8010
    while port in ports:
        port += 1
    return port


def ensure_dirs(app):
    # make sure the target directories exist (outside the container)
    try:
        app.dir.mkdir(parents=True, exist_ok=True)
        (app.dir / app.STATIC_DIR).mkdir(parents=True, exist_ok=True)
        (app.dir / app.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        return False


def create_database(app_env, db_name, user_name, replace=False):
    password = generate_password()
    db_name = db_name.replace('-', '_')
    user_name = user_name.replace('-', '_')
    # these statements take no parameters: quote the names, and the password may only contain letters and digits
    if not (password.isascii() and password.isalnum()):
        raise ValueError('generated password must only contain letters and digits')
    db, user = connection.ops.quote_name(db_name), connection.ops.quote_name(user_name)
    with connection.cursor() as cursor:
        if replace:
            cursor.execute(f'SET ROLE {user}')
            cursor.execute(f'DROP DATABASE IF EXISTS {db}')
            cursor.execute('RESET ROLE')
            cursor.execute(f'DROP USER IF EXISTS {user}')
        cursor.execute(f"CREATE USER {user} WITH PASSWORD '{password}'")
        cursor.execute(f"ALTER ROLE {user} SET client_encoding TO 'utf8'")
        cursor.execute(
            f"ALTER ROLE {user} SET default_transaction_isolation TO 'read committed'"
        )
        cursor.execute(f"ALTER ROLE {user} SET timezone TO 'Europe/Zurich'")
        cursor.execute(
            f'CREATE DATABASE {db} OWNER {user} '
            f"TEMPLATE template0 ENCODING 'UTF8' "
            f"LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8'"
        )
    app_env.juntagrico_database_host = 'localhost'
    app_env.juntagrico_database_name = db_name
    app_env.juntagrico_database_password = password
    app_env.juntagrico_database_port = '5432'
    app_env.juntagrico_database_user = user_name
    app_env.save()


def create_docker_file(app):
    with open(app.dir / 'Dockerfile', 'w') as docker_file:
        docker_file.write(
            get_template(f'infra/v{app.version}/Dockerfile').render({
                'app': app,
                'default_python_version': settings.DEFAULT_PYTHON_VERSION,
            })
        )
