import subprocess
from urllib import request as r, parse

from github import Github

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from adminconsole.config import Config
from adminconsole.models import GitHubKey, App


def github_request(request):
    return redirect('https://github.com/login/oauth/authorize?client_id=b420b562ea569fd26b6e&scope=public_repo')


def github_callback(request):
    code = request.GET.get('code')
    data_dict = {'code': code,
                 'client_id': 'b420b562ea569fd26b6e',
                 'client_secret': '40054b662fedbb506539aa8ab91031ca21383cb2'
                 }
    data = parse.urlencode(data_dict).encode()
    req = r.Request('https://github.com/login/oauth/access_token', data=data)
    resp = r.urlopen(req)
    key = str(resp.read()).split('&')[0].split('=')[1]
    GitHubKey.objects.create(user=request.user, key=key)
    return redirect('/ca/repo')


@login_required
def select_repo(request):
    key = request.user.githubkey.key
    g = Github(key)
    repos = g.get_user().get_repos()
    if request.method == 'POST':
        selected_repo = request.POST.get('repo')
        for repo in repos:
            if repo.name == selected_repo:
                request.session['git_clone_url'] = repo.clone_url
                return redirect('/ca/af')
    render_dict = {
        'repos': repos,
    }
    return render(request, 'repos.html', render_dict)


@login_required
def clone_repo(request):
    app = get_object_or_404(App, pk=request.session['app'])
    output = []
    directory = '/var/django/projects/' + app.name
    if not Config.test_localhost():
        key = request.user.githubkey.key
        url = 'https://' + key + ':x-oauth-basic@' + app.git_clone_url[8:]
    proc = subprocess.run(['mkdir', directory], stdout=subprocess.PIPE)
    output.append(str(proc.stdout))
    proc = subprocess.run(['mkdir', 'static'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    proc = subprocess.run(['mkdir', 'media'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    if not Config.test_localhost():
        proc = subprocess.run(['git', 'clone', url, 'code'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    render_dict = {
        'step': 'Repo Klonen',
        'next': '/ck/form',
    }
    if request.session.get('import',False):
        render_dict['next'] = '/ca/db'
    return render(request, 'done_next.html', render_dict)


@login_required
def git_push(request):
    app = get_object_or_404(App, pk=request.session['app'])
    directory = '/var/django/projects/' + app.name + '/code'
    output = []
    proc = subprocess.run(['git', 'add', '.', '--all'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'commit', '-a', '-m', '"adminconsole"'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'push'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    render_dict = {
        'step': 'Cokkiecutter anwenden und repo pushen',
        'next': '/ca/db'
    }
    return render(request, 'done_next.html', render_dict)
