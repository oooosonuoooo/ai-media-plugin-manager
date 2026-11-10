import json
import urllib.error
import unittest
from unittest.mock import Mock, patch

from scripts import doctor


class ComfyUIQueueTests(unittest.TestCase):
    def response(self, payload: bytes):
        response = Mock()
        response.read.return_value = payload
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_reports_idle_queue_and_uses_bounded_local_request(self):
        payload = json.dumps({"queue_running": [], "queue_pending": []}).encode()
        opener = Mock()
        opener.open.return_value = self.response(payload)
        with patch.object(doctor.urllib.request, "build_opener", return_value=opener) as build_opener:
            result = doctor.comfyui_queue_status("http://127.0.0.1:8188")

        self.assertEqual(result, {"status": "idle", "running": 0, "pending": 0})
        request, = opener.open.call_args.args
        self.assertEqual(request.full_url, "http://127.0.0.1:8188/queue")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], doctor.COMFYUI_TIMEOUT_SECONDS)
        handlers = build_opener.call_args.args
        self.assertTrue(any(isinstance(handler, doctor.NoRedirectHandler) for handler in handlers))
        self.assertTrue(any(
            isinstance(handler, doctor.urllib.request.ProxyHandler) and handler.proxies == {}
            for handler in handlers
        ))

    def test_reports_running_and_pending_counts(self):
        payload = json.dumps({"queue_running": [[1, "prompt"]], "queue_pending": [[2], [3]]}).encode()
        opener = Mock()
        opener.open.return_value = self.response(payload)
        with patch.object(doctor.urllib.request, "build_opener", return_value=opener):
            result = doctor.comfyui_queue_status("http://127.0.0.1:8188/")
        self.assertEqual(result, {"status": "busy", "running": 1, "pending": 2})

    def test_reports_api_failure_as_unavailable(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("connection refused")
        with patch.object(doctor.urllib.request, "build_opener", return_value=opener):
            result = doctor.comfyui_queue_status("http://127.0.0.1:8188")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("connection refused", result["error"])
        self.assertIsNone(result["running"])
        self.assertIsNone(result["pending"])

    def test_rejects_remote_and_credentialed_urls_before_opening(self):
        for base_url in (
            "http://example.com:8188",
            "http://user:secret@127.0.0.1:8188",
            "http://127.0.0.1:8188/api",
            "https://127.0.0.1:8188",
        ):
            with self.subTest(base_url=base_url):
                with patch.object(doctor.urllib.request, "build_opener") as build_opener:
                    result = doctor.comfyui_queue_status(base_url)
                self.assertEqual(result["status"], "unavailable")
                build_opener.assert_not_called()

    def test_rejects_malformed_or_oversized_queue_responses(self):
        for payload in (
            b'{"queue_running": []}',
            b"not json",
            b"x" * (doctor.COMFYUI_MAX_RESPONSE_BYTES + 1),
        ):
            with self.subTest(payload_length=len(payload)):
                opener = Mock()
                opener.open.return_value = self.response(payload)
                with patch.object(doctor.urllib.request, "build_opener", return_value=opener):
                    result = doctor.comfyui_queue_status("http://127.0.0.1:8188")
                self.assertEqual(result["status"], "unavailable")

    def test_redirect_handler_refuses_redirects(self):
        handler = doctor.NoRedirectHandler()
        request = doctor.urllib.request.Request("http://127.0.0.1:8188/queue")
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "http://example.com/"))


if __name__ == "__main__":
    unittest.main()
