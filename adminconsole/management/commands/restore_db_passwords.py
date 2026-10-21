from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from adminconsole.models import AppEnv


class Command(BaseCommand):
    help = (
        "Generate SQL to reset AppEnv PostgreSQL role passwords\n\n"
        "Usage: python manage.py generate_role_password_sql | "
        'psql -v ON_ERROR_STOP=1\n\n'
        "The default Django database connection reads AppEnv. "
        "SQL is streamed directly to psql; "
        "passwords are not printed to the terminal."
    )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The default Django database must be PostgreSQL.")

        with connection.cursor() as cursor:
            for role, password in (
                AppEnv.objects.using("default")
                .values_list("juntagrico_database_user", "juntagrico_database_password")
                .iterator()
            ):
                if not role or password is None:
                    continue

                # PostgreSQL format() quotes the role identifier and password literal.
                cursor.execute(
                    "SELECT format('ALTER ROLE %%I PASSWORD %%L;', %s, %s)",
                    [role, password],
                )
                self.stdout.write(cursor.fetchone()[0])
