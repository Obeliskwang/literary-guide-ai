import json
import tempfile
import unittest
from pathlib import Path
from auth_service import AuthService, AuthError, ACCESS_TTL, REFRESH_TTL
from chat_backend import ChatSettings


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [1700000000]
        self.service = AuthService(Path(self.tmp.name) / "auth.sqlite3", clock=lambda: self.now[0])
        self.service.initialize_demo_users()

    def login(self):
        return self.service.login("demo", "Demo@123456")

    def test_login_me_hashes_and_ttl(self):
        data = self.login()
        self.assertEqual(self.service.me(data["access_token"])["username"], "demo")
        self.assertEqual(data["user"]["nickname"], "Obeliskw")
        self.assertEqual(data["expires_in"], ACCESS_TTL)
        with self.service.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username='demo'").fetchone()
            self.assertTrue(user["password_hash"].startswith(b"$2"))
            row = db.execute("SELECT * FROM refresh_tokens").fetchone()
            self.assertNotEqual(row["token_hash"], data["refresh_token"])
            self.assertEqual(row["expires_at"] - row["created_at"], REFRESH_TTL)
        self.assertNotIn("password_hash", data["user"])

    def test_wrong_credentials_have_same_message(self):
        for username, password in [("demo", "wrong"), ("missing", "wrong"), ("demo", "x" * 73)]:
            with self.assertRaises(AuthError) as ctx:
                self.service.login(username, password)
            self.assertEqual(str(ctx.exception), "用户名或密码错误")

    def test_access_expiry_refresh_and_refresh_expiry(self):
        data = self.login()
        self.now[0] += ACCESS_TTL
        with self.assertRaises(AuthError):
            self.service.me(data["access_token"])
        refreshed = self.service.refresh(data["refresh_token"])
        self.assertEqual(self.service.me(refreshed["access_token"])["username"], "demo")
        self.now[0] = 1700000000 + REFRESH_TTL
        with self.assertRaises(AuthError):
            self.service.refresh(data["refresh_token"])

    def test_tampered_and_malformed_jwt(self):
        token = self.login()["access_token"]
        for invalid in ["invalid", token[:-8] + "AAAAAAAA", "a.b.c", None]:
            with self.assertRaises(AuthError):
                self.service.me(invalid)

    def test_duplicate_login_logout_only_revokes_current(self):
        first, second = self.login(), self.login()
        self.service.logout(first["refresh_token"])
        self.service.logout(first["refresh_token"])
        with self.assertRaises(AuthError):
            self.service.refresh(first["refresh_token"])
        with self.assertRaises(AuthError):
            self.service.me(first["access_token"])
        self.assertEqual(self.service.me(second["access_token"])["username"], "demo")

    def test_login_key_survives_new_browser_state_not_new_login(self):
        first, second = self.login(), self.login()
        settings = ChatSettings("api", "custom", "https://example.test", "test-user-key")
        self.service.save_model_settings(first["refresh_token"], settings)
        self.assertEqual(self.service.get_model_settings(first["refresh_token"]), settings)
        self.assertIsNone(self.service.get_model_settings(second["refresh_token"]))
        with self.service.connect() as db:
            dump = "\n".join(db.iterdump())
            self.assertNotIn("test-user-key", dump)
        sid = self.service.token_hash(first["refresh_token"])
        self.service.logout(first["refresh_token"])
        self.assertNotIn(sid, self.service.model_settings)

    def test_server_restart_keeps_login_and_encrypted_user_key(self):
        data = self.login()
        self.service.save_model_settings(data["refresh_token"], ChatSettings("api", "m", "https://example.test", "key"))
        self.assertTrue(self.service.settings_key_path.is_file())
        reopened = AuthService(self.service.path, clock=lambda: self.now[0])
        self.assertEqual(reopened.me(data["access_token"])["username"], "demo")
        self.assertEqual(reopened.get_model_settings(data["refresh_token"]).api_key, "key")
        reopened.logout(data["refresh_token"])
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM login_model_settings").fetchone()[0], 0)

    def test_demo_initialization_is_idempotent(self):
        self.service.initialize_demo_users()
        with self.service.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
