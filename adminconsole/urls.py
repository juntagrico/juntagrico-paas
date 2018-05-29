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
from django.urls import path
from django.contrib.auth.views import LoginView
from adminconsole import views

urlpatterns = [
    
    path('admin/', admin.site.urls),
    path('', views.home),
    path('github/request', views.github_request),
    path('github/callback', views.github_callback),
    path('ca/start', views.create_app),
    path('ca/import', views.import_app),
    path('ca/repo', views.select_repo),
    path('ca/clonerepo', views.clone_repo),
    path('accounts/login/', LoginView.as_view()),
    path('ck/form', views.cookiecutter_form),
    path('dom/form/<int:app_id>/', views.domain_form),
    path('dom/add/<int:pid>/', views.add_domain),
    path('git/push', views.git_push),
    path('ca/db', views.init_db),
    path('ca/env/form', views.env_form),
    path('ca/env/dist', views.env_dist2),
    path('ca/docker', views.docker2),
    path('pid/<int:pid>/', views.pidcheck),
    path('reload/<int:app_id>/', views.reload),
    path('env/<int:app_id>/', views.env),
    path('env/restart/<int:app_id>/', views.env_restart),
    path('ca/af', views.app_form),
    path('gdl/<int:app_id>/', views.generate_depot_list),
]
