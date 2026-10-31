#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for database..."
python manage.py migrate --noinput
echo "Migrations completed."

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput
echo "Static files collected."

# Create superuser if none exists
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "Checking for superuser..."
    python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', '$ADMIN_EMAIL', '$ADMIN_PASSWORD')
    print('Superuser created.')
else:
    print('Superuser already exists.')
"
fi

# Start gunicorn
echo "Starting gunicorn..."
exec gunicorn --access-logfile - --workers 1 --bind 0.0.0.0:8000 --timeout 60000 adminconsole.wsgi:application
