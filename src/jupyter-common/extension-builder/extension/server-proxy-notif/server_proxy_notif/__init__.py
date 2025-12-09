try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode: https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings
    warnings.warn("Importing 'server_proxy_notif' outside a proper installation.")
    __version__ = "dev"


def _jupyter_labextension_paths():
    return [{
        "src": "labextension",
        "dest": "server-proxy-notif"
    }]


def _jupyter_server_extension_points():
    return [{
        "module": "server_proxy_notif"
    }]


def _load_jupyter_server_extension(server_app):
    """Load the server extension"""
    from .handlers import setup_handlers

    setup_handlers(server_app.web_app)
    server_app.log.info("Registered server-proxy-notif server extension")
