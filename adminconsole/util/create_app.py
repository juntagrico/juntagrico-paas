import subprocess  # nosec: B404

from django.conf import settings
from django.db import connection
from django.db.utils import DatabaseError
from django.template.loader import get_template

from adminconsole.models import App, AppCronjob, Domain, get_available_cronjobs
from adminconsole.util import generate_password


def get_postgres_connection():
    """Create a separate connection to the 'postgres' database for admin operations.
    This avoids polluting the default Django connection with autocommit/transaction state.
    Import is lazy so the module loads cleanly even when psycopg is unavailable.
    """
    from django.db.backends.postgresql.base import DatabaseWrapper

    settings_dict = connection.settings_dict.copy()
    settings_dict['NAME'] = 'postgres'
    return DatabaseWrapper(settings_dict)


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

        if app.version < 3:
            # For version < 3 apps, the code directory is mounted read-only at /code/
            # and the static volume is mounted at /code/static/.  The static subdirectory
            # must exist inside the code directory so Docker can create the mount point
            # on top of the read-only overlay.
            (app.code_dir / app.STATIC_DIR).mkdir(parents=True, exist_ok=True)
            (app.code_dir / app.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        return False


def create_database(app_env, db_name, user_name, replace=False):
    """Create a database and user for an app (idempotent when replace=False).
    Uses a separate connection to the 'postgres' database so the default Django
    connection is never touched (avoids autocommit/SAVEPOINT issues).
    Returns True on success, False on failure (with error details printed).
    """
    try:
        password = generate_password()
        db_name = db_name.replace('-', '_')
        user_name = user_name.replace('-', '_')
        # these statements take no parameters: quote the names, and the password may only contain letters and digits
        if not (password.isascii() and password.isalnum()):
            raise ValueError('generated password must only contain letters and digits')
        db, user = (
            connection.ops.quote_name(db_name),
            connection.ops.quote_name(user_name),
        )
        # Use a separate connection so the default Django connection stays clean
        pg_conn = get_postgres_connection()
        try:
            pg_conn.connect()
            with pg_conn.cursor() as cursor:
                if replace:
                    # Only SET ROLE if the user exists (needed to drop its database)
                    cursor.execute(
                        f"SELECT 1 FROM pg_roles WHERE rolname = '{user_name}'"
                    )
                    if cursor.fetchone():
                        cursor.execute(f'SET ROLE {user}')
                        cursor.execute(f'DROP DATABASE IF EXISTS {db}')
                        cursor.execute('RESET ROLE')
                    cursor.execute(f'DROP USER IF EXISTS {user}')
                    cursor.execute(f'CREATE USER {user}')
                else:
                    # Idempotent: skip if user already exists
                    cursor.execute(
                        f"SELECT 1 FROM pg_roles WHERE rolname = '{user_name}'"
                    )
                    if not cursor.fetchone():
                        cursor.execute(f'CREATE USER {user}')
                # Always set password and alter role settings
                cursor.execute(f"ALTER ROLE {user} WITH PASSWORD '{password}'")
                cursor.execute(f"ALTER ROLE {user} SET client_encoding TO 'utf8'")
                cursor.execute(
                    f"ALTER ROLE {user} SET default_transaction_isolation TO 'read committed'"
                )
                cursor.execute(f"ALTER ROLE {user} SET timezone TO 'Europe/Zurich'")
            # CREATE DATABASE must run outside a transaction block
            pg_conn.autocommit = True
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
                if not cursor.fetchone():
                    cursor.execute(
                        f'CREATE DATABASE {db} OWNER {user} '
                        f"TEMPLATE template0 ENCODING 'UTF8' "
                        f"LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8'"
                    )
        finally:
            pg_conn.close()
        app_env.juntagrico_database_host = 'localhost'
        app_env.juntagrico_database_name = db_name
        app_env.juntagrico_database_password = password
        app_env.juntagrico_database_port = '5432'
        app_env.juntagrico_database_user = user_name
        app_env.save()
        return True
    except (ValueError, DatabaseError) as e:
        print(f'Datenbank erstellen fehlgeschlagen: {e}', flush=True)
        return False


def create_docker_file(app):
    with open(app.dir / 'Dockerfile', 'w') as docker_file:
        docker_file.write(
            get_template(f'infra/v{app.version}/Dockerfile').render({
                'app': app,
                'default_python_version': settings.DEFAULT_PYTHON_VERSION,
            })
        )


def write_domain_config(app, domain_name):
    """Write the nginx domain config file for the given domain.

    Sets supports_same_origin_referrer_policy to True for Juntagrico >= 2.0.11,
    which natively supports the same-origin referrer policy.
    """
    from packaging.version import Version

    supports_sorp = False
    if app.juntagrico_version:
        try:
            supports_sorp = Version(app.juntagrico_version) >= Version('2.0.11')
        except Exception:
            pass

    with open(f'/var/django/domains/{domain_name}', 'w') as domain_file:
        domain_file.write(
            get_template('infra/domain.txt').render({
                'name': app.name,
                'port': app.port,
                'domain': domain_name,
                'supports_same_origin_referrer_policy': supports_sorp,
            })
        )


def request_ssl_certificate(domain_name):
    """Request an SSL certificate for the given domain via certbot.
    Returns True on success, False on failure.
    """
    proc = subprocess.run(  # nosec: B603, B607
        ['sudo', '/usr/local/sbin/juntagrico-certbot', domain_name],
        stdout=subprocess.PIPE,
    )
    print(str(proc.stdout))
    return proc.returncode == 0


def setup_domain(app):
    """Create the default domain for an app and request an SSL certificate.
    Returns True on success, False on failure.
    """
    try:
        domain_name = f'{app.name}{settings.APPS_DOMAIN}'
        domain, _ = Domain.objects.get_or_create(
            name=domain_name, defaults={'app': app}
        )
        write_domain_config(app, domain_name)
        return request_ssl_certificate(domain_name)
    except (Domain.DoesNotExist, DatabaseError) as e:
        print(f'Domain erstellen fehlgeschlagen: {e}', flush=True)
        return False


def create_default_cronjobs(app):
    """Create default/required cronjobs for an app (idempotent)."""
    available = get_available_cronjobs(app.name)
    for cj_def in available:
        if cj_def.get('default') or cj_def.get('required'):
            timing = cj_def.get('timing', 'fixed')
            defaults = {}
            if timing == 'daily':
                defaults['hour'] = cj_def.get('default_hour', 23)
                dm = cj_def.get('default_minute', 0)
                defaults['minute'] = app.port % 60 if dm == 'spread' else dm
            elif timing == 'hourly':
                dm = cj_def.get('default_minute', 0)
                defaults['minute'] = app.port % 60 if dm == 'spread' else dm
            AppCronjob.objects.get_or_create(
                app=app, cronjob_id=cj_def['id'], defaults=defaults
            )
