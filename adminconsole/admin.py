from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from django.utils.html import format_html

from adminconsole.models import (
    GitHubKey,
    App,
    AppEnv,
    AppEnvVar,
    Domain,
    AppCronjob,
    JuntagricoVersion,
)


class AppCronjobInline(admin.TabularInline):
    model = AppCronjob
    extra = 1


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


class AppEnvVarInline(admin.TabularInline):
    model = AppEnvVar
    extra = 1


class AppEnvAdmin(admin.ModelAdmin):
    inlines = [AppEnvVarInline]


class AppAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'port',
        'wsgi',
        'python_version',
        'juntagrico_version',
        'managed',
        'version',
        'staging_of',
        'run_until',
        'isolated_network',
        'repo',
    ]
    search_fields = ['name', 'port']
    list_filter = ('python_version', 'version', 'isolated_network')
    inlines = [AppCronjobInline, DomainInline]
    readonly_fields = ['appenv_link']

    @admin.display(description='AppEnv bearbeiten')
    def appenv_link(self, obj):
        if hasattr(obj, 'env'):
            url = reverse('admin:adminconsole_appenv_change', args=[obj.env.id])
            return format_html('<a href="{url}">AppEnv bearbeiten</a>', url=url)
        return 'Keine AppEnv vorhanden'

    @admin.display(description='repo')
    def repo(self, obj):
        return format_html('<a href="{url}">Github</a>', url=obj.git_clone_url)


class DomainAdmin(admin.ModelAdmin):
    list_display = ['name', 'port', 'app']
    search_fields = ['name', 'app__name', 'app__port']

    @admin.display(description='port')
    def port(self, obj):
        return obj.app.port


def update_juntagrico_versions_action(modeladmin, request, queryset):
    """Admin action to trigger fetching juntagrico versions from PyPI."""
    call_command('update_juntagrico_versions')
    modeladmin.message_user(request, 'Juntagrico versions have been updated from PyPI.')


update_juntagrico_versions_action.short_description = (
    'Update juntagrico versions from PyPI'
)


@admin.register(JuntagricoVersion)
class JuntagricoVersionAdmin(admin.ModelAdmin):
    list_display = ['version']
    search_fields = ['version']
    actions = [update_juntagrico_versions_action]


admin.site.register(GitHubKey)
admin.site.register(App, AppAdmin)
admin.site.register(AppEnv, AppEnvAdmin)
admin.site.register(Domain, DomainAdmin)
admin.site.register(AppCronjob)
