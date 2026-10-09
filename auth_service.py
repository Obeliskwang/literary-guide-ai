"""Local demo authentication: bcrypt, signed HS256 JWT and revocable login sessions."""
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import bcrypt
from chat_backend import ChatSettings
from local_secrets import protect, unprotect

ROOT = Path(__file__).resolve().parent
ACCESS_TTL = 2 * 60 * 60
REFRESH_TTL = 7 * 24 * 60 * 60


class AuthError(Exception):
    def __init__(self, message="登录凭证无效或已过期", code=401):
        super().__init__(message)
        self.code = code


def response(data=None, code=0, message="成功"):
    return {"code": code, "message": message, "data": data}


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


class AuthService:
    def __init__(self, path=None, clock=time.time):
        self.path = Path(path or ROOT / "data" / "auth.sqlite3")
        self.settings_key_path = self.path.with_name("model-settings.key")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.RLock()
        self.model_settings = {}
        with self.connect() as db:
            db.executescript((ROOT / "auth_schema.sql").read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO auth_settings VALUES ('jwt_secret',?)", (secrets.token_hex(32),))
            self.secret = db.execute("SELECT value FROM auth_settings WHERE key='jwt_secret'").fetchone()[0].encode()
            db.execute("DELETE FROM login_model_settings WHERE token_hash IN (SELECT token_hash FROM refresh_tokens WHERE revoked_at IS NOT NULL OR expires_at<=?)", (int(self.clock()),))
        self.dummy_hash = bcrypt.hashpw(b"invalid-password", bcrypt.gensalt())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize_demo_users(self):
        for username, password, nickname, role in [("demo", "Demo@123456", "Obeliskw", "user"), ("admin", "Admin@123456", "演示管理员", "admin")]:
            with self.connect() as db:
                if not db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                    db.execute("INSERT OR IGNORE INTO users(username,password_hash,nickname,role) VALUES (?,?,?,?)", (username, bcrypt.hashpw(password.encode(), bcrypt.gensalt()), nickname, role))
                elif username == 'demo':
                    db.execute("UPDATE users SET nickname=? WHERE username=?", (nickname, username))

    @staticmethod
    def token_hash(token):
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise AuthError()
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def user_info(row):
        return {key: row[key] for key in ("id", "username", "nickname", "role")}

    def _access(self, user, sid):
        now = int(self.clock())
        header = _encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _encode(json.dumps({"sub": str(user["id"]), "sid": sid, "iat": now, "exp": now + ACCESS_TTL, "iss": "literary-demo", "aud": "literary-app"}, separators=(",", ":")).encode())
        body = header + "." + payload
        return body + "." + _encode(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or len(username) > 100 or not 1 <= len(password.encode()) <= 72:
            raise AuthError("用户名或密码错误")
        with self.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
            valid = bcrypt.checkpw(password.encode(), user["password_hash"] if user else self.dummy_hash)
            if not user or not valid:
                raise AuthError("用户名或密码错误")
            token = secrets.token_urlsafe(48)
            sid = self.token_hash(token)
            now = int(self.clock())
            db.execute("INSERT INTO refresh_tokens VALUES (?,?,?,?,NULL)", (sid, user["id"], now, now + REFRESH_TTL))
            info = self.user_info(user)
        return {"access_token": self._access(info, sid), "refresh_token": token, "token_type": "Bearer", "expires_in": ACCESS_TTL, "user": info}

    def _session(self, sid):
        with self.connect() as db:
            row = db.execute("SELECT u.id,u.username,u.nickname,u.role,r.expires_at,r.revoked_at FROM refresh_tokens r JOIN users u ON u.id=r.user_id WHERE token_hash=?", (sid,)).fetchone()
        if not row or row["revoked_at"] is not None or row["expires_at"] <= self.clock():
            with self.lock:
                self.model_settings.pop(sid, None)
                with self.connect() as db:
                    db.execute("DELETE FROM login_model_settings WHERE token_hash=?", (sid,))
            raise AuthError()
        return row

    def authenticated_session(self, refresh_token):
        sid = self.token_hash(refresh_token)
        return sid, self.user_info(self._session(sid))

    def me(self, access_token):
        try:
            if not isinstance(access_token, str) or len(access_token) > 4096:
                raise ValueError()
            header, payload, signature = access_token.split(".")
            body = (header + "." + payload).encode()
            if json.loads(_decode(header)) != {"alg": "HS256", "typ": "JWT"}:
                raise ValueError()
            if not hmac.compare_digest(_decode(signature), hmac.new(self.secret, body, hashlib.sha256).digest()):
                raise ValueError()
            claims = json.loads(_decode(payload))
            if claims["iss"] != "literary-demo" or claims["aud"] != "literary-app" or claims["exp"] <= self.clock():
                raise ValueError()
            user = self.user_info(self._session(claims["sid"]))
            if claims["sub"] != str(user["id"]):
                raise ValueError()
            return user
        except (ValueError, KeyError, TypeError):
            raise AuthError() from None

    def refresh(self, refresh_token):
        sid, user = self.authenticated_session(refresh_token)
        return {"access_token": self._access(user, sid), "token_type": "Bearer", "expires_in": ACCESS_TTL}

    def logout(self, refresh_token):
        sid = self.token_hash(refresh_token)
        with self.lock:
            with self.connect() as db:
                db.execute("UPDATE refresh_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (int(self.clock()), sid))
                db.execute("DELETE FROM login_model_settings WHERE token_hash=?", (sid,))
            self.model_settings.pop(sid, None)

    def save_model_settings(self, refresh_token, settings):
        settings.validate()
        with self.lock:
            sid, _ = self.authenticated_session(refresh_token)
            encrypted = protect(json.dumps({"mode": settings.mode, "model": settings.model, "base_url": settings.base_url, "api_key": settings.api_key}, ensure_ascii=False).encode(), self.settings_key_path)
            with self.connect() as db:
                db.execute("INSERT INTO login_model_settings VALUES (?,?) ON CONFLICT(token_hash) DO UPDATE SET protected_settings=excluded.protected_settings", (sid, encrypted))
            self.model_settings[sid] = settings

    def get_model_settings(self, refresh_token):
        with self.lock:
            sid, _ = self.authenticated_session(refresh_token)
            if sid not in self.model_settings:
                with self.connect() as db:
                    row = db.execute("SELECT protected_settings FROM login_model_settings WHERE token_hash=?", (sid,)).fetchone()
                if row:
                    self.model_settings[sid] = ChatSettings(**json.loads(unprotect(row[0], self.settings_key_path)))
            return self.model_settings.get(sid)

    def clear_model_settings(self, refresh_token):
        with self.lock:
            sid, _ = self.authenticated_session(refresh_token)
            with self.connect() as db:
                db.execute("DELETE FROM login_model_settings WHERE token_hash=?", (sid,))
            self.model_settings.pop(sid, None)


if __name__ == "__main__":
    service = AuthService()
    service.initialize_demo_users()
    print("初始化完成：demo / Demo@123456；admin / Admin@123456")
