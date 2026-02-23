from django.contrib import admin

from adminconsole.models import GitHubKey, App, AppEnv


class AppAdmin(admin.ModelAdmin):
    list_display = ['name', 'port', 'wsgi', 'python_version', 'managed', 'version', 'staging_of', 'run_until']
    search_fields = ['name', 'port']
    list_filter = ('python_version', 'version')


admin.site.register(GitHubKey)
admin.site.register(App, AppAdmin)
admin.site.register(AppEnv)
