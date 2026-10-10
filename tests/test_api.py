import json
import os
import subprocess
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen(["python", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8099"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:8099/health", timeout=1)
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        cls.server.terminate()
        cls.server.wait(timeout=10)
        raise RuntimeError("API failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)

    def test_authentication_and_probes(self):
        for path in ("health", "ready"):
            self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:8099/{path}").status, 200)
        with self.assertRaises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen("http://127.0.0.1:8099/forecasts")
        self.assertEqual(failure.exception.code, 401)
        request = urllib.request.Request("http://127.0.0.1:8099/forecasts", headers={"X-API-Key": os.environ["API_AUTH_TOKEN"]})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertIsInstance(json.load(response), list)

    def test_db_outage_does_not_fail_liveness_or_leak_details(self):
        from fastapi import HTTPException
        from api.main import health, ready
        with patch("api.main.get_engine", side_effect=RuntimeError("secret-in-exception")):
            self.assertEqual(health(), {"status": "ok"})
            with self.assertRaises(HTTPException) as failure:
                ready()
            self.assertEqual(failure.exception.status_code, 503)
            self.assertNotIn("secret-in-exception", failure.exception.detail)

    def test_auth_fails_closed_without_configuration(self):
        from fastapi import HTTPException
        from api.main import authenticate
        with patch.dict(os.environ, {"API_AUTH_TOKEN": ""}):
            with self.assertRaises(HTTPException) as failure:
                authenticate("anything")
            self.assertEqual(failure.exception.status_code, 503)
