from django.conf import settings


def test_localhost():
    """Return True if running in test mode with localhost."""
    if hasattr(settings, 'TEST_LOCALHOST'):
        return settings.TEST_LOCALHOST
    return False
