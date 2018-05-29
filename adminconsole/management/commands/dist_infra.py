import subprocess

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):

        parser.add_argument('app_name', nargs=1)

    # entry point used by manage.py
    def handle(self, *args, **options):
        name = options['app_name'][0]
        dir = '/var/django/projects/'+name
        bdir = '/var/django/projects/'+name+'/build'
        req = '/var/django/projects/'+name+'/code/requirements.txt'
        uri = name+'.juntagrico.science'
        rdir = '/root'
        
        proc = subprocess.run(['mv',bdir+'/docker-compose.yml',dir], stdout = subprocess.PIPE, cwd=bdir)
        print(str(proc.stdout))
        proc = subprocess.run(['mv',name, '/etc/nginx/sites-available'], stdout = subprocess.PIPE, cwd=bdir)
        print(str(proc.stdout))
        proc = subprocess.run(['ln', '-s', '/etc/nginx/sites-available/'+name, '/etc/nginx/sites-enabled'], stdout = subprocess.PIPE, cwd=bdir)
        print(str(proc.stdout))
        proc = subprocess.run(['cp',req, bdir], stdout = subprocess.PIPE, cwd=bdir)
        print(str(proc.stdout))
        proc = subprocess.run(['./certbot-auto', '--nginx', '--redirect', '--keep', '-n', '-d', uri], stdout = subprocess.PIPE, cwd=rdir)
        print(str(proc.stdout))
        proc = subprocess.run(['./certbot-auto', '--nginx', '--redirect', '--keep', '-n', '-d', uri], stdout = subprocess.PIPE, cwd=rdir)
        print(str(proc.stdout))
        proc = subprocess.run(['(crontab -l 2>/dev/null; echo "59 23 * * * docker exec '+name+' python -m manage generate_depot_list") | crontab -'], stdout = subprocess.PIPE, cwd=rdir)
        print(str(proc.stdout))
