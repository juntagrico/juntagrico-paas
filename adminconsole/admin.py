from django.contrib import admin
from django.utils.html import format_html

from adminconsole.models import GitHubKey, App, AppEnv, AppEnvVar, Domain, AppCronjob


class AppCronjobInline(admin.TabularInline):
    model = AppCronjob
    extra = 1


class AppEnvVarInline(admin.TabularInline):
    model = AppEnvVar
    extra = 1


class AppEnvAdmin(admin.ModelAdmin):
    inlines = [AppEnvVarInline]


class AppAdmin(admin.ModelAdmin):
    list_display = ['name', 'port', 'wsgi', 'python_version', 'juntagrico_version', 'managed', 'version', 'staging_of',
                    'run_until', 'repo']
    search_fields = ['name', 'port']
    list_filter = ('python_version', 'version')
    inlines = [AppCronjobInline]

    @admin.display(description="repo")
    def repo(self, obj):
        url = obj.git_clone_url.split('@')[0]
        return format_html('<a href="{url}">Github</a>', url=url)


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
