from decouple import config

DEBUG_TOOLBAR_ENABLED = config("DEBUG_TOOLBAR_ENABLED", default=True, cast=bool)
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": "config.settings.debug_toolbar.setup.show_toolbar",
}
