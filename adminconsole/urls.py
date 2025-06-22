"""adminconsole URL Configuration
"""
from django.contrib import admin
from django.urls import path, include
from adminconsole import views
from adminconsole.views import git, create

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('profile', views.profile, name='profile'),
    path('', views.home, name='home'),
    path('overview/<int:app_id>/', views.overview, name='overview'),
    path('ca/import', create.create_app, {'existing': True}, name='import'),
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

# create application urls in the right order how they flow
    path('ca/start', create.create_app),
    path('github/request', git.github_request),
    path('github/callback', git.github_callback),
    path('ca/repo', git.select_repo),
    path('ca/af', create.app_form),
    path('ca/clonerepo', git.clone_repo),
    path('ck/form', create.cookiecutter_form),
    path('git/push', git.git_push),
    path('ca/db', create.init_db),
    path('ca/ap', create.admin_password),
    path('ca/env/form', create.env_form),
    path('ca/env/dist', create.env_dist2),
    path('ca/docker', create.docker2),
]
