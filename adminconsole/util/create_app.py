import subprocess

from django.conf import settings
from django.db import connection
from django.template.loader import get_template

from adminconsole.config import Config
from adminconsole.models import App
from adminconsole.util import generate_password


def find_port():
    ports = App.objects.all().values_list('port', flat=True)
    port = 8010
    while port in ports:
        port += 1
    return port


def make_dirs(directory, output=None):
    result = True
    proc = subprocess.run(['mkdir', '-p', directory], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result &= proc.returncode == 0
    if output is not None:
        output.append(proc.stdout.decode())

    proc = subprocess.run(['mkdir', '-p', 'static'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=directory)
    result &= proc.returncode == 0
    if output is not None:
        output.append(proc.stdout.decode())

    proc = subprocess.run(['mkdir', '-p', 'media'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=directory)
    result &= proc.returncode == 0
    if output is not None:
        output.append(proc.stdout.decode())
    return result


def git_clone(key, app, output=None):
    if not Config.test_localhost():
        url = 'https://' + key + ':x-oauth-basic@' + app.git_clone_url[8:]
        proc = subprocess.run(['git', 'clone', '--depth=1', url, 'code'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=app.dir)
        if output is not None:
            output.append(proc.stdout.decode())
        return proc.returncode == 0
    return True


def create_database(app_env, db_name, user_name):
    password = generate_password()
    db_name = db_name.replace('-', '_')
    user_name = user_name.replace('-', '_')
    with connection.cursor() as cursor:
        cursor.execute("CREATE DATABASE " + db_name)
        cursor.execute("CREATE USER " + user_name + " WITH PASSWORD '" + password + "'")
        cursor.execute("ALTER ROLE " + user_name + " SET client_encoding TO 'utf8'")
        cursor.execute("ALTER ROLE " + user_name + " SET default_transaction_isolation TO 'read committed'")
        cursor.execute("ALTER ROLE " + user_name + " SET timezone TO 'CET'")
        cursor.execute("GRANT ALL PRIVILEGES ON DATABASE " + db_name + " TO " + user_name)
    app_env.juntagrico_database_host = 'localhost'
    app_env.juntagrico_database_name = db_name
    app_env.juntagrico_database_password = password
    app_env.juntagrico_database_port = '5432'
    app_env.juntagrico_database_user = user_name
    app_env.save()


def clone_database(staging_app, output=None):
    if not staging_app.staging_of:
        if output is not None:
            output.append(f'{staging_app.name} is not a staging app')
        return False
    db_user = settings.DATABASES['default']['USER']
    db_pw = settings.DATABASES['default']['PASSWORD']
    dump = subprocess.Popen(['pg_dump', '-U', db_user, '--no-password', staging_app.staging_of.env.juntagrico_database_name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={'PGPASSWORD': db_pw})
    proc = subprocess.run(['psql', '-U', db_user, '--no-password', staging_app.env.juntagrico_database_name],
                          stdin=dump.stdout, stderr=subprocess.PIPE, env={'PGPASSWORD': db_pw})
    dump.wait()
    if output is not None:
        dump_err = dump.communicate()[1]
        if dump_err:
            output.append(dump_err.decode())
        if proc.stderr:
            output.append(proc.stderr.decode())
    return dump.returncode == 0 and proc.returncode == 0


def create_docker_file(app):
    with open(app.dir / 'Dockerfile', "w") as docker_file:
        docker_file.write(get_template('build/Dockerfile').render({'app': app}))
