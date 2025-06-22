from functools import wraps

from django.shortcuts import get_object_or_404, redirect

from adminconsole.models import App


def owner_of_app(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            user = request.user
            app_id = kwargs['app_id'] or user.app.first().id
            app = get_object_or_404(App, id=app_id)
            if app.user.id == user.id or user.is_superuser:
                return view(request, *args, **kwargs)
            else:
                return redirect('home')
        else:
            return redirect('login')

    return wrapper