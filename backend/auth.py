"""Access-token scoped facade for existing encrypted per-login configuration."""
import json
import os
from urllib.parse import urlsplit
from auth_service import AuthService, _decode
from chat_backend import ChatSettings
from local_secrets import protect, unprotect
from .contracts import Error


class Auth:
    def __init__(self, path, default_settings=None):
        self.service = AuthService(path)
        self.service.initialize_demo_users()
        self.default_settings = default_settings

    def context(self, token):
        user = self.service.me(token)
        sid = json.loads(_decode(token.split('.')[1]))['sid']
        return user, sid

    def defaults(self):
        if self.default_settings is not None:
            return self.default_settings
        from config import LLM_TYPE, AI_MODEL_NAME, AI_BASE_URL, AI_API_KEY, OLLAMA_LLM_MODEL
        return ChatSettings('api', AI_MODEL_NAME, AI_BASE_URL, AI_API_KEY) if LLM_TYPE in ('api', 'openai') else ChatSettings('ollama', OLLAMA_LLM_MODEL, 'http://localhost:11434')

    def settings(self, sid):
        service = self.service
        with service.lock:
            service._session(sid)
            with service.connect() as db:
                row = db.execute('SELECT protected_settings FROM login_model_settings WHERE token_hash=?', (sid,)).fetchone()
            return ChatSettings(**json.loads(unprotect(row[0], service.settings_key_path))) if row else self.defaults()

    def summary(self, sid):
        settings = self.settings(sid)
        with self.service.connect() as db:
            saved = db.execute('SELECT 1 FROM login_model_settings WHERE token_hash=?', (sid,)).fetchone()
        return dict(mode=settings.mode, model=settings.model, base_url=settings.base_url, has_api_key=bool(settings.api_key), source='login' if saved else 'default')

    def save(self, sid, body):
        key = body.api_key.get_secret_value() if body.api_key is not None else ''
        if body.mode == 'api' and not key:
            old = self.settings(sid)
            # Omitted key may reuse only an already saved configuration at the same endpoint.
            if self.summary(sid)['source'] != 'login' or old.mode != 'api' or old.base_url.rstrip('/') != body.base_url.strip().rstrip('/'):
                raise Error(422, 'VALIDATION_ERROR', '远程配置首次保存或更换地址时必须填写密钥')
            key = old.api_key
        settings = ChatSettings(body.mode, body.model.strip(), body.base_url.strip(), key)
        try:
            settings.validate()
        except ValueError:
            raise Error(422, 'VALIDATION_ERROR', '模型配置无效') from None
        allowed = os.getenv('LITERARY_MODEL_HOSTS', '')
        if allowed and urlsplit(settings.base_url).hostname not in allowed.split(','):
            raise Error(403, 'FORBIDDEN', '模型地址不在服务器允许范围内')
        with self.service.lock:
            self.service._session(sid)
            protected = protect(json.dumps(settings.__dict__).encode(), self.service.settings_key_path)
            with self.service.connect() as db:
                db.execute('INSERT INTO login_model_settings VALUES (?,?) ON CONFLICT(token_hash) DO UPDATE SET protected_settings=excluded.protected_settings', (sid, protected))
            self.service.model_settings.pop(sid, None)
        return self.summary(sid)

    def clear(self, sid):
        with self.service.lock:
            self.service._session(sid)
            with self.service.connect() as db:
                db.execute('DELETE FROM login_model_settings WHERE token_hash=?', (sid,))
            self.service.model_settings.pop(sid, None)
        return {'cleared': True}
