from django.conf import settings


class Config:
    def __init__(self):
        pass

    @staticmethod
    def test_localhost():
        if hasattr(settings, 'TEST_LOCALHOST'):
            return settings.TEST_LOCALHOST
        return False

    @staticmethod
    def report_email():
        if hasattr(settings, 'REPORT_EMAIL'):
            return settings.REPORT_EMAIL
        return None
