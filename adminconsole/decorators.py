from functools import wraps

from django.shortcuts import get_object_or_404, redirect

from adminconsole.models import App, Domain


def owner_of_app(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            user = request.user
            app = get_object_or_404(App, id=kwargs['app_id'])
            if app.user.id == user.id or user.is_superuser:
                return view(request, *args, **kwargs)
            else:
                return redirect('home')
        else:
            return redirect('login')

    return wrapper


def owner_of_domain(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            user = request.user
            if user.is_superuser or Domain.objects.filter(id=kwargs['domain_id'], app__user=user).exists():
                return view(request, *args, **kwargs)
            else:
                return redirect('home')
        else:
            return redirect('login')

    return wrapper