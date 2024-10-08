import subprocess
from urllib import request as r, parse

from django.conf import settings
from github import Github, BadCredentialsException

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from adminconsole.config import Config
from adminconsole.models import GitHubKey, App


def github_request(request):
    return redirect(f'https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}&scope=public_repo')


def github_callback(request):
    code = request.GET.get('code')
    data_dict = {
        'code': code,
        'client_id': settings.GITHUB_CLIENT_ID,
        'client_secret': settings.GITHUB_CLIENT_SECRET
    }
    data = parse.urlencode(data_dict).encode()
    req = r.Request('https://github.com/login/oauth/access_token', data=data)
    resp = r.urlopen(req)
    key = str(resp.read()).split('&')[0].split('=')[1]
    GitHubKey.objects.update_or_create(user=request.user, defaults={'key': key})
    return redirect('/ca/repo')


@login_required
def select_repo(request):
    key = request.user.githubkey.key
    g = Github(key)

    if request.method == 'POST':
        selected_repo = int(request.POST.get('repo'))
        request.session['git_clone_url'] = g.get_repo(selected_repo).clone_url
        return redirect('/ca/af')

    # show repos
    repos = g.get_user().get_repos()
    try:
        # check if key is still valid
        repos[0]
    except BadCredentialsException:
        return redirect('/github/request')
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
    if request.session.get('import', False):
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
