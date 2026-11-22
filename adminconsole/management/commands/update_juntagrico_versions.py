"""Fetch juntagrico versions from PyPI and update the database.

This command queries the PyPI JSON API for all juntagrico releases,
then stores only the latest stable (non-prerelease) bugfix release per
major.minor line that is >= the configured minimum version.

Can be triggered manually, via cron, or as a Django admin action.
"""

import json
import logging
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand
from packaging.version import Version

from adminconsole.models import JuntagricoVersion

logger = logging.getLogger('adminconsole.audit')


def fetch_latest_versions_from_pypi():
    """Fetch the latest stable bugfix release per major.minor from PyPI.

    Returns a list of version strings containing only the latest stable
    release per major.minor line that is >= the configured minimum version.
    """
    req = urllib.request.Request(
        'https://pypi.org/pypi/juntagrico/json',
        headers={'Accept': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode('utf-8'))

    releases = data.get('releases', {})
    min_ver = Version(settings.JUNTAGRICO_MIN_VERSION)

    # Find the latest stable release per major.minor
    latest_by_major_minor = {}
    for version_str in releases:
        try:
            ver = Version(version_str)
        except Exception:
            continue
        # Skip pre-releases
        if ver.is_prerelease:
            continue
        # Skip versions below minimum
        if ver < min_ver:
            continue
        mm = (ver.major, ver.minor)
        if mm not in latest_by_major_minor or ver > Version(latest_by_major_minor[mm]):
            latest_by_major_minor[mm] = version_str

    return list(latest_by_major_minor.values())


class Command(BaseCommand):
    help = 'Fetch juntagrico versions from PyPI and update the database.'

    def handle(self, *args, **options):
        self.stdout.write('Fetching juntagrico versions from PyPI...')
        try:
            versions = fetch_latest_versions_from_pypi()
        except Exception as e:
            self.stderr.write(f'Error fetching from PyPI: {e}')
            logger.error('Failed to fetch juntagrico versions from PyPI: %s', e)
            return

        if not versions:
            self.stderr.write('No versions found from PyPI.')
            return

        self.stdout.write(
            f'Found {len(versions)} latest stable versions >= '
            f'{settings.JUNTAGRICO_MIN_VERSION}.'
        )

        # Update database records
        created = 0
        updated = 0
        for version_str in versions:
            obj, created_flag = JuntagricoVersion.objects.update_or_create(
                version=version_str,
                defaults={},
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        # Remove versions no longer the latest
        kept_versions = set(versions)
        removed = JuntagricoVersion.objects.exclude(version__in=kept_versions).delete()[
            0
        ]
        if removed:
            self.stdout.write(f'Removed {removed} outdated version records.')

        self.stdout.write(
            f'Updated database: {created} created, {updated} existing, '
            f'{removed} removed.'
        )
        logger.info(
            'juntagrico versions updated from PyPI: %d created, %d updated, %d removed',
            created,
            updated,
            removed,
        )
