"""
Django test settings for CI with PostgreSQL.
Based on dev_settings.py but configured for PostgreSQL service in GitHub Actions.
"""

import os

from dev_settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'test'),
        'USER': os.environ.get('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        'HOST': 'localhost',
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}
