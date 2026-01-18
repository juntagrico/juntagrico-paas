"""adminconsole URL Configuration
"""
from django.contrib import admin
from django.urls import path, include
from adminconsole import views
from adminconsole.views import git, create, staging, v2, app

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('profile', views.profile, name='profile'),
    path('', views.home, name='home'),
    path('overview/<int:app_id>/', views.overview, name='overview'),
    path('app/<int:app_id>/start/', app.start, name='app-start'),
    path('app/<int:app_id>/stop/', app.stop, name='app-stop'),
    path('dom/form/<int:app_id>/', views.domain_form),
    path('mailtexts/<int:app_id>/', views.mailtexts),
    path('showlog/<int:app_id>/', views.show_log),
    path('show/<int:app_id>/result/', views.show_result, name='show-result'),
    path('logs/<int:app_id>/', views.logs, name='login'),
    path('versions/<int:app_id>/', views.versions, name='versions'),
    path('dom/add/<int:pid>/', views.add_domain),
    path('pid/<int:pid>/', views.pidcheck),
    path('reload/<int:app_id>/', views.reload, name='redeploy'),
    path('env/<int:app_id>/', views.env),
    path('env/restart/<int:app_id>/', views.env_restart),
    path('gdl/<int:app_id>/', views.generate_depot_list),
    path('migrate/<int:app_id>/', views.migrate),
    path('collectstatic/<int:app_id>/', views.collectstatic),
    path('crestart/<int:app_id>/', views.restart),
    path('rebuild/<int:app_id>/', views.rebuild_image, name='rebuild-image'),
    path('branch/change/<int:app_id>/', views.change_branch, name='change-branch'),
    path('dumpdata/<int:app_id>/', views.dumpdata, name='dumpdata'),
    path('pgdump/<int:app_id>/', views.pgdump, name='pgdump'),

    # create application urls in the right order how they flow
    path('ca/af', create.app_form, name='create-app'),
    path('github/request', git.github_request, name='github-access'),
    path('github/callback', git.github_callback),
    path('ca/repo/<int:app_id>/', git.select_repo, name='github-select'),
    path('ca/clonerepo/<int:app_id>/', git.clone_repo, name='ca-git-clone'),
    path('ca/overwrite/<int:app_id>/', create.overwrite_app, name='ca-overwrite'),
    path('ck/form/<int:app_id>/', create.cookiecutter_form, name='ca-cookiecutter'),
    path('git/push/<int:app_id>/', git.git_push, name='ca-git-push'),
    path('ca/db/<int:app_id>/', create.init_db, name='ca-init-db'),
    path('ca/ap/<int:app_id>/', create.admin_password, name='ca-admin-pw'),
    path('ca/env/form/<int:app_id>/', create.env_form, name='ca-create-env'),
    path('ca/env/dist/<int:app_id>/', create.env_dist2, name='ca-init-env'),
    path('ca/docker/<int:app_id>/', create.docker2, name='ca-build-docker'),

    # staging app
    path('staging/create/<int:app_id>/', staging.create, name='staging-create'),
    path('staging/git/clone/<int:app_id>/', staging.clone_repo, name='staging-git-clone'),
    path('staging/db/init/<int:app_id>/', staging.init_db, name='staging-init-db'),
    path('staging/domain/init/<int:app_id>/', staging.init_domain, name='staging-init-domain'),
    path('staging/db/clone/<int:app_id>/', staging.clone_db, name='staging-clone-db'),
    path('staging/renew/<int:app_id>/', staging.renew, name='staging-renew'),

    # v2 apps
    path('v2/redeploy/<int:app_id>/', v2.redeploy, name='redeploy-v2'),
    path('v2/upgrade/<int:app_id>/', v2.redeploy, {'upgrade': True}, name='upgrade-v2'),
    path('v2/python/version/set/<int:app_id>/', v2.set_python_version, name='set-python-version'),
    path('v2/version/set/<int:app_id>/', v2.set_version, name='set-version'),
]
