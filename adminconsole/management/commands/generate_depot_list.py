from django.core.management.base import BaseCommand



class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs='1')

    # entry point used by manage.py
    def handle(self, *args, **options):
        
