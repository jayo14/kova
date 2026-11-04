import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from celery.signals import worker_ready

logger = logging.getLogger(__name__)

_worker_is_ready = False
_server_started = False
_server_lock = threading.Lock()


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        status = b"ok" if _worker_is_ready else b"ok (worker starting)"
        self.wfile.write(status)

    def log_message(self, *a):
        pass


def start_health_server() -> None:
    global _server_started
    role = os.environ.get("KOVA_ROLE", "api").lower()
    # In 'api' or 'all' mode, Uvicorn already serves HTTP traffic on $PORT.
    if role in ("api", "all"):
        return

    port_str = os.environ.get("PORT") or os.environ.get("WORKER_HEALTH_PORT")
    if not port_str:
        return

    with _server_lock:
        if _server_started:
            return
        try:
            port = int(port_str)
            server = HTTPServer(("0.0.0.0", port), _H)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            _server_started = True
            logger.info("Worker health HTTP server listening on 0.0.0.0:%d", port)
        except Exception as exc:
            logger.warning("Failed to start worker health HTTP server on port %s: %s", port_str, exc)


@worker_ready.connect
def _on_worker_ready(**_):
    global _worker_is_ready
    _worker_is_ready = True
    start_health_server()
    logger.info("Worker ready signal received, health status updated")


# Eagerly start health server on module load if in worker role and PORT is configured
start_health_server()
