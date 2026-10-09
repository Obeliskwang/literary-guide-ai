import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode
from auth_service import AuthService
from auth_api import make_server


class AuthAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        service = AuthService(Path(self.tmp.name) / "auth.sqlite3")
        service.initialize_demo_users()
        self.server = make_server(service, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
            result = connection.getresponse()
            return result.status, json.loads(result.read()), dict(result.getheaders())
        finally:
            connection.close()

    def test_four_endpoints(self):
        status, login, _ = self.request("POST", "/api/auth/login", {"username": "demo", "password": "Demo@123456"})
        self.assertEqual(status, 200)
        self.assertEqual(set(login), {"code", "message", "data"})
        status, me, _ = self.request("GET", "/api/auth/me", headers={"Authorization": "Bearer " + login["data"]["access_token"]})
        self.assertEqual(me["data"]["role"], "user")
        status, refreshed, _ = self.request("POST", "/api/auth/refresh", {"refresh_token": login["data"]["refresh_token"]})
        self.assertEqual(refreshed["code"], 0)
        status, logout, headers = self.request("POST", "/api/auth/logout", {"refresh_token": login["data"]["refresh_token"]})
        self.assertEqual(logout["code"], 0)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        status, invalid, _ = self.request("GET", "/api/auth/me", headers={"Authorization": "Bearer " + refreshed["data"]["access_token"]})
        self.assertEqual((status, invalid["code"]), (401, 401))

    def test_errors_and_missing_bearer(self):
        status, value, _ = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 401)
        for username in ["demo", "unknown"]:
            status, value, _ = self.request("POST", "/api/auth/login", {"username": username, "password": "bad"})
            self.assertEqual(value["message"], "用户名或密码错误")
        status, value, _ = self.request("POST", "/api/auth/login", [])
        self.assertEqual(status, 400)
        status, value, _ = self.request("POST", "/api/auth/login", {"username": "demo"})
        self.assertEqual((status, value["code"]), (400, 400))

    def test_browser_login_sets_http_only_cookie(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", "/login")
        result = connection.getresponse()
        page = result.read().decode()
        cookie = result.getheader("Set-Cookie").split(";", 1)[0]
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        connection.request("POST", "/login", body=urlencode({"username": "demo", "password": "Demo@123456", "csrf": csrf}), headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"})
        result = connection.getresponse()
        result.read()
        self.assertEqual(result.status, 303)
        cookies = [v for k, v in result.getheaders() if k.lower() == "set-cookie"]
        self.assertTrue(any("literary_refresh=" in c and "HttpOnly" in c and "SameSite=Strict" in c for c in cookies))
        self.assertEqual(result.getheader("Location"), "http://localhost:8501")

    def test_login_assets_and_path_boundary(self):
        for name, content_type in [("style.css", "text/css"), ("script.js", "application/javascript"), ("book-illustration.png", "image/png")]:
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            try:
                connection.request("GET", "/static/login/" + name)
                result = connection.getresponse()
                self.assertEqual(result.status, 200)
                self.assertIn(content_type, result.getheader("Content-Type"))
                self.assertTrue(result.read())
            finally:
                connection.close()
        status, _, _ = self.request("GET", "/static/login/../../config.py")
        self.assertEqual(status, 404)
