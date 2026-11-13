from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allow only logged-in users whose role is in `roles`.

    Logged-out users go to the login page (via @login_required).
    Logged-in users with a different role get a 403 page, so typing
    another role's dashboard URL does not work.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("Your account role cannot open this page.")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
