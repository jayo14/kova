import os
import unittest
from unittest.mock import patch, MagicMock
from app.workers import health_server


class TestHealthServer(unittest.TestCase):
    def setUp(self):
        health_server._server_started = False
        health_server._worker_is_ready = False

    def test_health_server_skipped_for_api_or_all(self):
        with patch.dict(os.environ, {"KOVA_ROLE": "api", "PORT": "9999"}):
            with patch("app.workers.health_server.HTTPServer") as mock_http:
                health_server.start_health_server()
                mock_http.assert_not_called()

        with patch.dict(os.environ, {"KOVA_ROLE": "all", "PORT": "9999"}):
            with patch("app.workers.health_server.HTTPServer") as mock_http:
                health_server.start_health_server()
                mock_http.assert_not_called()

    def test_health_server_starts_in_worker_mode_with_port(self):
        with patch.dict(os.environ, {"KOVA_ROLE": "worker", "PORT": "8888"}):
            with patch("app.workers.health_server.HTTPServer") as mock_http:
                with patch("threading.Thread") as mock_thread:
                    thread_instance = MagicMock()
                    mock_thread.return_value = thread_instance
                    health_server.start_health_server()
                    mock_http.assert_called_once_with(("0.0.0.0", 8888), health_server._H)
                    thread_instance.start.assert_called_once()
                    self.assertTrue(health_server._server_started)

    def test_worker_ready_updates_state(self):
        self.assertFalse(health_server._worker_is_ready)
        health_server._on_worker_ready()
        self.assertTrue(health_server._worker_is_ready)
