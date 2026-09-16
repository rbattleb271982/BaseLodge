"""Gunicorn lifecycle hooks for the best-effort PostHog client."""


def post_fork(_server, _worker):
    """Never reuse a client or delivery thread inherited from the master."""
    from analytics import _reset_client_after_fork

    _reset_client_after_fork()


def worker_exit(_server, _worker):
    """Attempt buffered analytics delivery at orderly worker shutdown."""
    from analytics import _shutdown_client

    _shutdown_client()