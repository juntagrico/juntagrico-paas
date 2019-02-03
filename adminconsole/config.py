from django.conf import settings


class Config:
    def __init__(self):
        pass

    @staticmethod
    def test_localhost():
        if hasattr(settings, 'TEST_LOCALHOST'):
            return settings.TEST_LOCALHOST
        return False
