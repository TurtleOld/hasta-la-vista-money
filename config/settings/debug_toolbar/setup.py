import logging

from django.urls import include, path

try:
    import debug_toolbar
except ImportError:
    debug_toolbar = None

logger = logging.getLogger('configuration')


def show_toolbar() -> bool:
    """
    The general idea is the following:

    1. We show the toolbar if we have it installed & we have it
       configured to be shown.
        - This opens up the option to move the dependency as a local one,
          if one chooses to do so.
    2. This function acts as the single source of truth of that.
        - No additional checks elsewhere are required.

    This means we can have the following options possible:

    - Show on a production environments.
    - Exclude the entire dependency from production environments.
    - Have the flexibility to control the debug toolbar via a single
      Django setting.

    Additionally, we don't want to deal with the INTERNAL_IPS thing.
    """
    from .settings import DEBUG_TOOLBAR_ENABLED  # noqa: PLC0415

    if not DEBUG_TOOLBAR_ENABLED:
        return False

    if debug_toolbar is None:
        logger.info('No installation found for: django_debug_toolbar')
        return False

    return True


class DebugToolbarSetup:
    """
    We use a class, just for namespacing convenience.
    """

    @staticmethod
    def do_settings(
        installed_apps: list[str],
        middleware: list[str],
        middleware_position: int | None = None,
    ) -> tuple[list[str], list[str]]:
        _show_toolbar: bool = show_toolbar()
        logger.info('Django Debug Toolbar in use: %s', _show_toolbar)

        if not _show_toolbar:
            return installed_apps, middleware

        installed_apps = [*installed_apps, 'debug_toolbar']

        # In order to deal with that:
        # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#add-the-middleware
        # The order of MIDDLEWARE is important.
        # You should include the Debug Toolbar middleware as early as
        # possible in the list.
        # However, it must come after any other middleware that encodes
        # the response's content, such as GZipMiddleware.
        # We support inserting the middleware at an arbitrary position
        # in the list.
        # If position is not specified, we will just include it at the
        # end of the list.

        debug_toolbar_middleware = (
            'debug_toolbar.middleware.DebugToolbarMiddleware'
        )

        if middleware_position is None:
            middleware = [*middleware, debug_toolbar_middleware]
        else:
            # Grab a new copy of the list, since insert mutates the
            # internal structure
            _middleware = middleware[::]
            _middleware.insert(middleware_position, debug_toolbar_middleware)

            middleware = _middleware

        return installed_apps, middleware

    @staticmethod
    def do_urls(urlpatterns):
        if not show_toolbar():
            return urlpatterns

        import debug_toolbar  # noqa: PLC0415

        return [*urlpatterns, path('__debug__/', include(debug_toolbar.urls))]
