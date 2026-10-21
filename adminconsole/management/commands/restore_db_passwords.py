from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from adminconsole.models import AppEnv


class Command(BaseCommand):
    help = "Reset PostgreSQL role passwords from AppEnv."

    # ALTER ROLE affects the database beyond a transaction; run statements directly.
    requires_system_checks = []
    output_transaction = False

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The default Django database must be PostgreSQL.")

        updated = 0
        skipped = 0

        try:
            with connection.cursor() as cursor:
                for env in AppEnv.objects.all().iterator():
                    role = env.juntagrico_database_user
                    password = env.juntagrico_database_password

                    if not role or password is None:
                        skipped += 1
                        continue

                    # PostgreSQL's format() safely quotes the role as an identifier
                    # and the password as a string literal.
                    cursor.execute(
                        "SELECT format('ALTER ROLE %I PASSWORD %L', %s, %s)",
                        [role, password],
                    )
                    alter_statement = cursor.fetchone()[0]
                    cursor.execute(alter_statement)
                    updated += 1

        except Exception as exc:
            raise CommandError(
                "Could not reset the role passwords. Check that the default "
                "database connection has permission to alter those roles."
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(f"Updated {updated} role(s); skipped {skipped}.")
        )
