"""Home Assistant ingress: the UI is served inside the HA sidebar through the Supervisor's proxy.

The proxy strips its prefix (/api/hassio_ingress/<token>) before forwarding and sends
it in X-Ingress-Path. Setting SCRIPT_NAME from it makes url_for() build links that
work in the browser. Home Assistant has already logged the user in, so only
requests from the proxy itself are accepted.
"""

SUPERVISOR_PROXY = "172.30.32.2"
LOOPBACK = {"127.0.0.1", "::1"}  # the container's own health check


class IngressMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        remote = environ.get("REMOTE_ADDR")
        if remote != SUPERVISOR_PROXY and remote not in LOOPBACK:
            start_response("403 Forbidden", [("Content-Type", "text/plain")])
            return [b"Open Photo Organiser from the Home Assistant sidebar."]
        prefix = environ.get("HTTP_X_INGRESS_PATH", "").rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
        return self.app(environ, start_response)
