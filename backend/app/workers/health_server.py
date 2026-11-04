import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from celery.signals import worker_ready

logger = logging.getLogger(__name__)


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@worker_ready.connect
def _start_health(**_):
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), _H)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info("Worker health HTTP server listening on 0.0.0.0:%d", port)
    except Exception as exc:
        logger.warning("Failed to start worker health HTTP server on port %s: %s", port_str, exc)
