from django.contrib import admin
from django.utils.html import format_html

from adminconsole.models import GitHubKey, App, AppEnv, Domain


class AppAdmin(admin.ModelAdmin):
    list_display = ['name', 'port', 'wsgi', 'python_version', 'managed', 'version', 'staging_of', 'run_until', 'repo']
    search_fields = ['name', 'port']
    list_filter = ('python_version', 'version')

    @admin.display(description="repo")
    def repo(self, obj):
        url = obj.git_clone_url.split('@')[0]
        return format_html('<a href="{url}">Github</a>', url=url)


admin.site.register(GitHubKey)
admin.site.register(App, AppAdmin)
admin.site.register(AppEnv)
admin.site.register(Domain)
