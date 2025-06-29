import subprocess
from urllib import request as r, parse

from django.conf import settings
from django.urls import reverse
from github import Github, BadCredentialsException

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from adminconsole.decorators import owner_of_app
from adminconsole.models import GitHubKey, App
from adminconsole.util.create_app import make_dirs
from adminconsole.util.git import git_clone


@login_required
def github_request(request):
    return redirect(f'https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}&scope=public_repo')


@login_required
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
    return redirect(request.session.pop('next', 'home'))


@owner_of_app
def select_repo(request, app_id):
    key = request.user.githubkey.key
    g = Github(key)

    if request.method == 'POST':
        selected_repo = int(request.POST.get('repo'))
        App.objects.filter(pk=app_id).update(git_clone_url=g.get_repo(selected_repo).clone_url)
        return redirect('ca-git-clone', app_id=app_id)

    # show repos
    repos = g.get_user().get_repos()
    try:
        # check if key is still valid
        repos[0]
    except BadCredentialsException:
        request.session['next'] = request.path
        return redirect('github-access')

    return render(request, 'repos.html', {
        'repos': repos,
    })


@owner_of_app
def clone_repo(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    if not app.git_clone_url:
        return redirect('github-select', app_id=app_id)
    if not request.user.githubkey.key:
        request.session['next'] = request.path
        return redirect('github-access')

    errors = []
    success = make_dirs(app.dir, errors)
    if success:
        success &= git_clone(request.user.githubkey.key, app, errors)

    return render(request, 'done_next.html', {
        'errors': '' if success else errors,
        'step': 'Repo Klonen',
        'next': reverse('ca-overwrite', args=[app_id]),
    })


@owner_of_app
def git_push(request, app_id):
    app = get_object_or_404(App, pk=app_id)
    directory = app.dir / 'code'
    output = []
    proc = subprocess.run(['git', 'add', '.', '--all'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'commit', '-a', '-m', '"adminconsole"'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))
    proc = subprocess.run(['git', 'push'], stdout=subprocess.PIPE, cwd=directory)
    output.append(str(proc.stdout))

    return render(request, 'done_next.html', {
        'step': 'Cokkiecutter anwenden und repo pushen',
        'next': reverse('ca-init-db', args=[app_id])
    })
