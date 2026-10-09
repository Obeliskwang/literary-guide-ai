"""Local HTTP auth endpoints and cookie-based demo login page."""
import html
import json
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from pathlib import Path
from auth_service import AuthError, AuthService, REFRESH_TTL, response

COOKIE = "literary_refresh"
LOGIN_DIR = Path(__file__).resolve().parent / "static" / "login"
LOGIN_ASSETS = {
    "/static/login/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/login/script.js": ("script.js", "application/javascript; charset=utf-8"),
    "/static/login/book-illustration.png": ("book-illustration.png", "image/png"),
}


def make_server(service, port=8000, app_url="http://localhost:8501"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log credentials, cookies or submitted request bodies.

        def send(self, body, status=200, content_type="application/json; charset=utf-8", cookies=(), redirect=None):
            payload = body if isinstance(body, bytes) else body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(payload)))
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            if redirect:
                self.send_header("Location", redirect)
            self.end_headers()
            self.wfile.write(payload)

        def cookies(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            return {key: value.value for key, value in cookie.items()}

        def login_page(self, message=""):
            csrf = secrets.token_urlsafe(32)
            page = (LOGIN_DIR / "index.html").read_text(encoding="utf-8")
            page = page.replace("{{CSRF}}", html.escape(csrf, quote=True)).replace("{{MESSAGE}}", html.escape(message))
            self.send(page, content_type="text/html; charset=utf-8", cookies=[f"literary_csrf={csrf}; HttpOnly; SameSite=Strict; Path=/; Max-Age=600"])

        def body(self, form=False):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError()
                raw = self.rfile.read(length).decode("utf-8")
                value = {key: vals[0] for key, vals in parse_qs(raw).items()} if form else json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
            except (ValueError, UnicodeError):
                raise AuthError("请求参数格式错误", 400) from None

        def do_GET(self):
            try:
                if self.path in LOGIN_ASSETS:
                    filename, content_type = LOGIN_ASSETS[self.path]
                    return self.send((LOGIN_DIR / filename).read_bytes(), content_type=content_type)
                if self.path == "/login":
                    return self.login_page()
                if self.path == "/api/auth/me":
                    header = self.headers.get("Authorization", "")
                    if not header.startswith("Bearer "):
                        raise AuthError()
                    return self.send(response(service.me(header[7:])))
                self.send(response(code=404, message="接口不存在"), 404)
            except AuthError as exc:
                self.send(response(code=exc.code, message=str(exc)), exc.code)
            except Exception:
                self.send(response(code=500, message="服务错误"), 500)

        def do_POST(self):
            try:
                if self.path == "/login":
                    body = self.body(form=True)
                    cookie_csrf = self.cookies().get("literary_csrf", "")
                    if not cookie_csrf or not secrets.compare_digest(cookie_csrf, body.get("csrf", "")):
                        raise AuthError("登录表单已过期，请重新打开登录页", 403)
                    try:
                        data = service.login(body.get("username"), body.get("password"))
                    except AuthError:
                        return self.login_page("用户名或密码错误")
                    return self.send("", 303, cookies=[f"{COOKIE}={data['refresh_token']}; HttpOnly; SameSite=Strict; Path=/; Max-Age={REFRESH_TTL}", "literary_csrf=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"], redirect=app_url)
                body = self.body()
                if self.path == "/api/auth/login":
                    if not isinstance(body.get("username"), str) or not isinstance(body.get("password"), str):
                        raise AuthError("请提供 username 和 password", 400)
                    data = service.login(body.get("username"), body.get("password"))
                elif self.path == "/api/auth/refresh":
                    data = service.refresh(body.get("refresh_token"))
                elif self.path == "/api/auth/logout":
                    service.logout(body.get("refresh_token"))
                    return self.send(response(), cookies=[f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"])
                else:
                    return self.send(response(code=404, message="接口不存在"), 404)
                self.send(response(data))
            except AuthError as exc:
                self.send(response(code=exc.code, message=str(exc)), exc.code)
            except Exception:
                self.send(response(code=500, message="服务错误"), 500)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def start_server(service, port=8000):
    server = make_server(service, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    service = AuthService()
    service.initialize_demo_users()
    print("鉴权 API：http://localhost:8000；登录页：http://localhost:8000/login")
    make_server(service).serve_forever()
