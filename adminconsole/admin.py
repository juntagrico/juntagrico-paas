from django.contrib import admin

from adminconsole.models import GitHubKey, App, AppEnv


admin.site.register(GitHubKey)
admin.site.register(App)
admin.site.register(AppEnv)
