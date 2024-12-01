"""adminconsole URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
v    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, PasswordResetView
from adminconsole import views
from adminconsole import views_git
from adminconsole import views_ca
urlpatterns = [
    
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('profile', views.profile, name='profile'),
    path('', views.home, name='home'),
    path('overview/<int:app_id>/', views.overview, name='overview'),
    path('ca/import', views_ca.import_app),
    path('dom/form/<int:app_id>/', views.domain_form),
    path('mailtexts/<int:app_id>/', views.mailtexts),
    path('showlog/<int:app_id>/', views.show_log),
    path('logs/<int:app_id>/', views.logs, name='login'),
    path('versions/<int:app_id>/', views.versions, name='versions'),
    path('dom/add/<int:pid>/', views.add_domain),
    path('pid/<int:pid>/', views.pidcheck),
    path('reload/<int:app_id>/', views.reload),
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
    path('ca/start', views_ca.create_app),
    path('github/request', views_git.github_request),
    path('github/callback', views_git.github_callback),
    path('ca/repo', views_git.select_repo),
    path('ca/af', views_ca.app_form),
    path('ca/clonerepo', views_git.clone_repo),
    path('ck/form', views_ca.cookiecutter_form),
    path('git/push', views_git.git_push),
    path('ca/db', views_ca.init_db),
    path('ca/ap', views_ca.admin_password),
    path('ca/env/form', views_ca.env_form),
    path('ca/env/dist', views_ca.env_dist2),
    path('ca/docker', views_ca.docker2),

]
