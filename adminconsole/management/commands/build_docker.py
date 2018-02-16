import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)
        parser.add_argument('pass', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        passw = options['pass'][0]
        dir = '/var/django/projects/'+name
        crss = 'from django.contrib.auth.models import User; User.objects.create_superuser("admin", "admin@admin.com", "'+ passw +'")'
        proc = subprocess.run(['docker-compose','build'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','up','-d'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'migrate'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'shell', '-c', crss],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'create_member_for_superusers'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
        proc = subprocess.run(['docker-compose','exec', name ,'python', '-m', 'manage', 'collectstatic'],stdout = subprocess.PIPE, cwd=dir)
        print(str(proc.stdout))
