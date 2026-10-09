import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from auth_service import AuthService, AuthError
from chat_backend import ChatSettings
import auth_ui


SCRIPT = '''
import streamlit as st
from auth_ui import require_login, render_chat_settings
from chat_backend import ChatSettings
service, token, user = require_login()
settings = render_chat_settings(service, token, ChatSettings("api", "project-model", "https://project.test", "project-key"), "local-model", "bge-m3")
st.write("selected:" + settings.model)
'''


class AuthUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = AuthService(Path(self.tmp.name) / "auth.sqlite3")
        self.service.initialize_demo_users()
        self.token = self.service.login("demo", "Demo@123456")["refresh_token"]
        self.runtime = patch.object(auth_ui, "auth_runtime", return_value=(self.service, None))
        self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.context = patch.object(st, "context", types.SimpleNamespace(cookies={"literary_refresh": self.token}))
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_defaults_and_key_survives_page_refresh_then_logout(self):
        page = AppTest.from_string(SCRIPT, default_timeout=15).run()
        self.assertFalse(page.exception)
        self.assertIn("selected:project-model", [v.value for v in page.markdown])
        page.text_input[0].set_value("user-model")
        page.text_input[1].set_value("https://user.test")
        page.text_input[2].set_value("user-key")
        page.button[1].click().run()
        self.assertFalse(page.exception)
        self.assertEqual(self.service.get_model_settings(self.token).model, "user-model")
        refreshed = AppTest.from_string(SCRIPT, default_timeout=15).run()
        self.assertFalse(refreshed.exception)
        self.assertIn("selected:user-model", [v.value for v in refreshed.markdown])
        self.assertEqual(refreshed.text_input[2].value, "")
        refreshed.button[0].click().run()
        self.assertFalse(refreshed.exception)
        with self.assertRaises(AuthError):
            self.service.authenticated_session(self.token)
        self.assertEqual(self.service.model_settings, {})

    def test_empty_key_resets_entire_project_configuration(self):
        self.service.save_model_settings(self.token, ChatSettings("api", "user-model", "https://user.test", "user-key"))
        page = AppTest.from_string(SCRIPT, default_timeout=15).run()
        page.button[1].click().run()
        self.assertFalse(page.exception)
        self.assertIsNone(self.service.get_model_settings(self.token))
        self.assertIn("selected:project-model", [v.value for v in page.markdown])

    def test_full_app_requires_login_before_ollama_check(self):
        with patch.object(st, "context", types.SimpleNamespace(cookies={})), patch("ollama_check.ensure_ollama_models") as check:
            page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
            self.assertFalse(page.exception)
            self.assertEqual(page.title[0].value, "伴读精灵 · 请先登录")
            check.assert_not_called()
