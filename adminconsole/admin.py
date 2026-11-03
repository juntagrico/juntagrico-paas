from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from adminconsole.models import GitHubKey, App, AppEnv, AppEnvVar, Domain, AppCronjob


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
    list_display = ['name', 'port', 'wsgi', 'python_version', 'juntagrico_version', 'managed', 'version', 'staging_of',
                    'run_until', 'isolated_network', 'repo']
    search_fields = ['name', 'port']
    list_filter = ('python_version', 'version', 'isolated_network')
    inlines = [AppCronjobInline, DomainInline]
    readonly_fields = ['appenv_link']

    @admin.display(description="AppEnv bearbeiten")
    def appenv_link(self, obj):
        if hasattr(obj, 'env'):
            url = reverse('admin:adminconsole_appenv_change', args=[obj.env.id])
            return format_html('<a href="{url}">AppEnv bearbeiten</a>', url=url)
        return 'Keine AppEnv vorhanden'

    @admin.display(description="repo")
    def repo(self, obj):
        return format_html('<a href="{url}">Github</a>', url=obj.git_clone_url)


class DomainAdmin(admin.ModelAdmin):
    list_display = ['name', 'port', 'app']
    search_fields = ['name', 'app__name', 'app__port']

    @admin.display(description="port")
    def port(self, obj):
        return obj.app.port


admin.site.register(GitHubKey)
admin.site.register(App, AppAdmin)
admin.site.register(AppEnv, AppEnvAdmin)
admin.site.register(Domain, DomainAdmin)
admin.site.register(AppCronjob)
