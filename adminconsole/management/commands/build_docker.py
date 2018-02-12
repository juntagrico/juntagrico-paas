import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs='1')

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name']
        dir = '/var/django/projects/'+name
        proc = subprocess.run(['docker-compose','build'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','run','-d'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'migrate'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'createsuperuser', '--username', 'admin', '--email', 'admin@admin.ch'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'create_member_for_superusers'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'collectstatic'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
