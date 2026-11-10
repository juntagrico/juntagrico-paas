"""adminconsole URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from two_factor.urls import urlpatterns as two_factor_urls

from adminconsole.views import (
    git,
    create,
    staging,
    v2,
    app,
    tools,
    domain,
    cronjob,
    generic,
)

urlpatterns = [
    path('', include(two_factor_urls)),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('profile', generic.profile, name='profile'),
    path('', generic.home, name='home'),
    path('overview/<int:app_id>/', app.overview, name='overview'),
    path('app/<int:app_id>/start/', app.start, name='app-start'),
    path('app/<int:app_id>/stop/', app.stop, name='app-stop'),
    path(
        'app/<int:app_id>/admin-password/',
        app.reset_admin_password,
        name='app-admin-password',
    ),
    path('mailtexts/<int:app_id>/', app.mailtexts),
    path('show/<int:app_id>/result/', app.show_result, name='show-result'),
    path('logs/<int:app_id>/', app.logs, name='logs'),
    path('versions/<int:app_id>/', app.versions, name='versions'),
    path('dom/form/<int:app_id>/', domain.manage, name='domain-manage'),
    path('dom/add/<int:app_id>/<int:pid>/', domain.add, name='domain-add'),
    path('dom/renew/<int:domain_id>/', domain.renew, name='domain-renew'),
    path('dom/remove/<int:domain_id>/', domain.remove, name='domain-remove'),
    path('cron/form/<int:app_id>/', cronjob.manage, name='cronjob-manage'),
    path('pid/<int:pid>/', generic.pidcheck),
    path('env/<int:app_id>/', app.env),
    path('env/show/<int:app_id>/', app.show_env, name='show-env'),
    path('gdl/<int:app_id>/', app.generate_depot_list),
    path('branch/change/<int:app_id>/', app.change_branch, name='change-branch'),
    path('dumpdata/<int:app_id>/', app.dumpdata, name='dumpdata'),
    path('pgdump/<int:app_id>/', app.pgdump, name='pgdump'),
    path(
        'app/<int:app_id>/create-cache-table/',
        app.create_cache_table,
        name='create-cache-table',
    ),
    # create application urls in the right order how they flow
    path('ca/af', create.app_form, name='create-app'),
    path('ca/source/<int:app_id>/', git.repo_source, name='repo-source'),
    path('ca/repo/<int:app_id>/', git.select_repo, name='github-select'),
    path('github/callback', git.github_callback, name='github-callback'),
    path('ca/clonerepo/<int:app_id>/', git.clone_repo, name='ca-git-clone'),
    path('ca/overwrite/<int:app_id>/', create.overwrite_app, name='ca-overwrite'),
    path('ck/form/<int:app_id>/', create.cookiecutter_form, name='ca-cookiecutter'),
    path('ca/env/form/<int:app_id>/', create.env_form, name='ca-create-env'),
    # staging app
    path('staging/create/<int:app_id>/', staging.create, name='staging-create'),
    path('staging/result/<int:app_id>/', staging.result, name='staging-result'),
    path('staging/db/clone/<int:app_id>/', staging.clone_db, name='staging-clone-db'),
    path('staging/renew/<int:app_id>/', staging.renew, name='staging-renew'),
    # v2 apps
    path('v2/redeploy/<int:app_id>/', v2.redeploy, name='redeploy-v2'),
    path('v2/upgrade/<int:app_id>/', v2.redeploy, {'upgrade': True}, name='upgrade-v2'),
    path('v2/progress/<int:app_id>/<int:pid>/', v2.show_progress, name='progress'),
    path(
        'v2/python/version/set/<int:app_id>/',
        v2.set_python_version,
        name='set-python-version',
    ),
    path('v2/version/set/<int:app_id>/', v2.set_version, name='set-version'),
    # tools
    path(
        'tools/update_permissions/<int:app_id>/',
        tools.update_permissions,
        name='update-permissions',
    ),
    path(
        'tools/sanitize_richtext/<int:app_id>/',
        tools.sanitize_richtext,
        name='sanitize-richtext',
    ),
    path('tools/reload_versions', tools.reload_versions, name='reload-versions'),
]
