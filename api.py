"""FastAPI entry point: python -m uvicorn api:create_app --factory --port 8000."""
import html
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException
from auth_service import AuthError, REFRESH_TTL
from backend.auth import Auth
from backend.books import Books, MAX_COVER_BYTES, MAX_FILE_BYTES
from backend.business import Business
from backend.exercises import SelfTests
from backend.contracts import ExerciseStart, ExerciseSubmit
from backend.conversations import Conversations
from backend.contracts import (Book, BookDetail, BookUpdate, Character, Envelope, Error, Event, Exercise, FileInfo, Graph, Items, Login, ModelInput, Relation,
                              ModelSummary, Name, Page, Preferences, Question, Refresh, Session, SessionInput, Tokens, Turn, User)
from backend.database import Database
from backend.runtime import ROOT, RagAdapter, process_lock
from config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
COOKIE = 'literary_refresh'
security = HTTPBearer(auto_error=False)
Key = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128)]
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def create_app(data_dir=None, adapter=None, default_settings=None):
    data_dir = Path(data_dir or os.getenv('LITERARY_DATA_DIR', str(ROOT / 'data'))).resolve()
    adapter = adapter or RagAdapter(ROOT)

    @asynccontextmanager
    async def lifespan(app):
        with process_lock(data_dir / 'api.lock'):
            app.state.database = Database(data_dir / 'service.sqlite3')
            app.state.auth = Auth(data_dir / 'auth.sqlite3', default_settings)
            app.state.books = Books(app.state.database, adapter)
            app.state.business = Business(app.state.database, adapter.root)
            app.state.conversations = Conversations(app.state.database, adapter, app.state.auth, app.state.business)
            app.state.self_tests = SelfTests(app.state.database, app.state.business)
            app.state.database.recover_questions()
            app.state.books.recover()
            yield

    app = FastAPI(title='伴读精灵业务 API', version='1.0.0', lifespan=lifespan,
                  description='独立后端；业务凭证使用 Authorize 输入 access token。创建/上传/问答必须提供 Idempotency-Key。')

    def envelope(request, data=None, code=0, message='成功'):
        return dict(code=code, message=message, data=data, request_id=request.state.request_id)

    @app.middleware('http')
    async def request_context(request, call_next):
        request.state.request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(Error)
    async def business_error(request, exc):
        return JSONResponse(envelope(request, exc.data, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        return JSONResponse(envelope(request, code='INVALID_CREDENTIALS' if request.url.path.endswith('/login') else 'AUTH_REQUIRED', message=str(exc)), status_code=exc.code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{'field': '.'.join(map(str, x['loc'])), 'reason': x['type']} for x in exc.errors()]
        return JSONResponse(envelope(request, {'errors': errors}, 'VALIDATION_ERROR', '请求参数无效'), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(envelope(request, code='RESOURCE_NOT_FOUND' if exc.status_code == 404 else 'INVALID_REQUEST', message='接口不存在' if exc.status_code == 404 else '请求无效'), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error('API failed: request_id=%s type=%s', request.state.request_id, type(exc).__name__)
        return JSONResponse(envelope(request, code='INTERNAL_ERROR', message='服务错误，请联系管理员并提供 request_id'), status_code=500, headers={'X-Request-ID': request.state.request_id})

    def context(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if credentials is None:
            raise Error(401, 'AUTH_REQUIRED', '请先登录')
        return request.app.state.auth.context(credentials.credentials)

    Context = Annotated[tuple, Depends(context)]

    def result(request, response, value):
        data, status, replayed = value
        response.status_code = status
        if replayed:
            response.headers['Idempotency-Replayed'] = 'true'
        return envelope(request, data)

    # Shared error models are shown on each business operation in Swagger.
    error_responses = {status: {'model': Envelope[dict], 'description': label} for status, label in (
        (400, '请求或文档无效'), (401, '凭证失效'), (403, '权限不足'), (404, '资源不可访问'),
        (409, '处理中/幂等冲突/数据不可用'), (410, '原问答历史已删除'), (413, '文件或文本超限'), (415, '不支持格式'),
        (422, '参数校验失败'), (500, '服务错误'), (502, '模型错误'), (503, '依赖不可用/保存待重试'), (504, '上游超时'))}
    from fastapi import APIRouter
    router = APIRouter(prefix='/api', responses=error_responses)

    @app.get('/health/live', response_model=Envelope[dict], tags=['健康检查'])
    def live(request: Request):
        return envelope(request, {'alive': True})

    @app.get('/health/ready', response_model=Envelope[dict], tags=['健康检查'])
    def ready(request: Request, check_models: bool = False):
        with app.state.database.tx() as db:
            dirty = db.execute("SELECT COUNT(*) FROM books WHERE status!='ready'").fetchone()[0]
        if dirty:
            raise Error(503, 'RECOVERY_PENDING', '部分资源等待恢复')
        if check_models:
            try:
                adapter.ready()
            except Exception:
                raise Error(503, 'DEPENDENCY_UNAVAILABLE', '本地嵌入服务尚未就绪') from None
        return envelope(request, {'ready': True, 'models_checked': check_models})

    @router.post('/auth/login', response_model=Envelope[Tokens], tags=['鉴权'])
    def login(body: Login, request: Request):
        return envelope(request, app.state.auth.service.login(body.username, body.password.get_secret_value()))

    @router.post('/auth/refresh', response_model=Envelope[Tokens], tags=['鉴权'])
    def refresh(body: Refresh, request: Request):
        token = body.refresh_token.get_secret_value()
        data = app.state.auth.service.refresh(token)
        data['refresh_token'] = token  # Existing implementation deliberately does not rotate refresh tokens.
        return envelope(request, data)

    @router.post('/auth/logout', response_model=Envelope[dict], tags=['鉴权'])
    def logout(body: Refresh, request: Request, response: Response):
        app.state.auth.service.logout(body.refresh_token.get_secret_value())
        response.delete_cookie(COOKIE, path='/')
        return envelope(request, {'logged_out': True})

    @router.get('/auth/me', response_model=Envelope[User], tags=['鉴权'])
    def me(request: Request, ctx: Context):
        return envelope(request, ctx[0])

    @router.get('/auth/model-settings', response_model=Envelope[ModelSummary], tags=['模型配置'])
    def model_settings(request: Request, ctx: Context):
        return envelope(request, app.state.auth.summary(ctx[1]))

    @router.put('/auth/model-settings', response_model=Envelope[ModelSummary], tags=['模型配置'])
    def save_model_settings(body: ModelInput, request: Request, ctx: Context):
        return envelope(request, app.state.auth.save(ctx[1], body))

    @router.delete('/auth/model-settings', response_model=Envelope[dict], tags=['模型配置'])
    def clear_model_settings(request: Request, ctx: Context):
        return envelope(request, app.state.auth.clear(ctx[1]))

    @router.get('/books', response_model=Envelope[Page[Book]], tags=['书籍'])
    def list_books(request: Request, ctx: Context, q: Annotated[str, Query(max_length=100)] = '', page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.books.list(ctx[0], q, page, page_size))

    @router.post('/books', response_model=Envelope[Book], status_code=201, tags=['书籍'])
    def create_book(body: Name, request: Request, response: Response, ctx: Context, key: Key):
        return result(request, response, app.state.books.create(ctx[0], body.name, key))

    @router.get('/books/{book_id}', response_model=Envelope[BookDetail], tags=['书籍'])
    def get_book(book_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.books.get(ctx[0], book_id))

    @router.patch('/books/{book_id}', response_model=Envelope[BookDetail], tags=['书籍'])
    def rename_book(book_id: str, body: BookUpdate, request: Request, ctx: Context):
        return envelope(request, app.state.books.update(ctx[0], book_id, body.model_dump(exclude_unset=True)))

    @router.put('/books/{book_id}/cover', response_model=Envelope[BookDetail], tags=['书籍'])
    def save_book_cover(book_id: str, request: Request, ctx: Context, file: UploadFile = File(...)):
        try:
            raw = file.file.read(MAX_COVER_BYTES + 1)
            return envelope(request, app.state.books.set_cover(ctx[0], book_id, raw, file.content_type or ''))
        finally:
            file.file.close()

    @router.get('/books/{book_id}/cover', response_class=Response, tags=['书籍'])
    def get_book_cover(book_id: str, ctx: Context):
        raw, content_type = app.state.books.cover(ctx[0], book_id)
        return Response(raw, media_type=content_type, headers={'Cache-Control': 'private, max-age=60'})

    @router.delete('/books/{book_id}', response_model=Envelope[dict], tags=['书籍'])
    def delete_book(book_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.books.delete(ctx[0], book_id))

    @router.post('/books/{book_id}/files', response_model=Envelope[FileInfo], status_code=201, responses={200: {'model': Envelope[FileInfo], 'description': '同内容文件已存在'}}, tags=['文件'])
    def upload(book_id: str, request: Request, response: Response, ctx: Context, key: Key, file: UploadFile = File(...)):
        with app.state.database.tx() as db:
            app.state.database.book(db, ctx[0], book_id, True)
        try:
            raw = file.file.read(MAX_FILE_BYTES + 1)
            return result(request, response, app.state.books.upload(ctx[0], book_id, file.filename, raw, key))
        finally:
            file.file.close()

    @router.delete('/books/{book_id}/files/{file_id}', response_model=Envelope[dict], tags=['文件'])
    def delete_file(book_id: str, file_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.books.delete_file(ctx[0], book_id, file_id))

    @router.get('/books/{book_id}/sessions', response_model=Envelope[Page[Session]], tags=['会话'])
    def list_sessions(book_id: str, request: Request, ctx: Context, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.conversations.list(ctx[0], book_id, page, page_size))

    @router.post('/books/{book_id}/sessions', response_model=Envelope[Session], status_code=201, tags=['会话'])
    def create_session(book_id: str, body: SessionInput, request: Request, response: Response, ctx: Context, key: Key):
        return result(request, response, app.state.conversations.create(ctx[0], book_id, body.name, key))

    @router.patch('/sessions/{session_id}', response_model=Envelope[Session], tags=['会话'])
    def rename_session(session_id: str, body: Name, request: Request, ctx: Context):
        return envelope(request, app.state.conversations.rename(ctx[0], session_id, body.name))

    @router.delete('/sessions/{session_id}', response_model=Envelope[dict], tags=['会话'])
    def delete_session(session_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.conversations.delete(ctx[0], session_id))

    @router.get('/sessions/{session_id}/messages', response_model=Envelope[Page[Turn]], tags=['会话'])
    def messages(session_id: str, request: Request, ctx: Context, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.conversations.history(ctx[0], session_id, page, page_size))

    @router.delete('/sessions/{session_id}/messages', response_model=Envelope[dict], tags=['会话'])
    def clear_messages(session_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.conversations.delete(ctx[0], session_id, True))

    @router.post('/sessions/{session_id}/questions', response_model=Envelope[Turn], status_code=201, tags=['问答'])
    def ask(session_id: str, body: Question, request: Request, response: Response, ctx: Context, key: Key):
        return result(request, response, app.state.conversations.ask(ctx[0], ctx[1], session_id, body.question, key))

    @router.get('/me/preferences', response_model=Envelope[Preferences], tags=['偏好'])
    def preferences(request: Request, ctx: Context):
        return envelope(request, app.state.conversations.preferences(ctx[0]))

    @router.put('/me/preferences', response_model=Envelope[Preferences], tags=['偏好'])
    def save_preferences(body: Preferences, request: Request, ctx: Context):
        return envelope(request, app.state.conversations.preferences(ctx[0], body))

    @router.get('/books/{book_id}/characters', response_model=Envelope[Page[Character]], tags=['人物关系'])
    def characters(book_id: str, request: Request, ctx: Context, family: Annotated[str | None, Query(max_length=100)] = None, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.business.characters(ctx[0], book_id, family, page, page_size))

    @router.get('/books/{book_id}/characters/{character_id}', response_model=Envelope[Character], tags=['人物关系'])
    def character(book_id: str, character_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.character(ctx[0], book_id, character_id))

    @router.get('/books/{book_id}/characters/{character_id}/relations', response_model=Envelope[Items[Relation]], tags=['人物关系'])
    def relations(book_id: str, character_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.relations(ctx[0], book_id, character_id))

    @router.get('/books/{book_id}/families', response_model=Envelope[Items[str]], tags=['人物关系'])
    def families(book_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.families(ctx[0], book_id))

    @router.get('/books/{book_id}/events', response_model=Envelope[Page[Event]], tags=['人物关系'])
    def events(book_id: str, request: Request, ctx: Context, character_id: str | None = None, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.business.events(ctx[0], book_id, character_id, page, page_size))

    @router.get('/books/{book_id}/events/{event_id}', response_model=Envelope[Event], tags=['人物关系'])
    def event(book_id: str, event_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.event(ctx[0], book_id, event_id))

    @router.get('/books/{book_id}/relationship-graph', response_model=Envelope[Graph], tags=['人物关系'])
    def graph(book_id: str, request: Request, ctx: Context, scope: Literal['all', 'character', 'family'] = 'all', character_id: str | None = None):
        return envelope(request, app.state.business.graph(ctx[0], book_id, scope, character_id))

    @router.get('/books/{book_id}/exercises', response_model=Envelope[Page[Exercise]], tags=['练习题'])
    def exercises(book_id: str, request: Request, ctx: Context, chapter: Annotated[str | None, Query(max_length=100)] = None, difficulty: Literal['easy', 'medium', 'hard'] | None = None, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.business.exercises(ctx[0], book_id, chapter, difficulty, page, page_size))

    @router.get('/books/{book_id}/exercises/{exercise_id}', response_model=Envelope[Exercise], tags=['练习题'])
    def exercise(book_id: str, exercise_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.exercise(ctx[0], book_id, exercise_id))

    @router.get('/books/{book_id}/exercise-chapters', response_model=Envelope[Items[str]], tags=['练习题'])
    def chapters(book_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.business.chapters(ctx[0], book_id))

    @router.post('/books/{book_id}/exercise-attempts', response_model=Envelope[dict], tags=['习题自测'])
    def start_exercise(book_id: str, payload: ExerciseStart, request: Request, response: Response, ctx: Context, key: Key):
        return result(request, response, app.state.self_tests.start(ctx[0], book_id, payload.model_dump(), key))

    @router.post('/books/{book_id}/exercise-attempts/{attempt_id}/submit', response_model=Envelope[dict], tags=['习题自测'])
    def submit_exercise(book_id: str, attempt_id: str, payload: ExerciseSubmit, request: Request, ctx: Context):
        return envelope(request, app.state.self_tests.submit(ctx[0], book_id, attempt_id, payload.answers))

    @router.get('/books/{book_id}/exercise-attempts', response_model=Envelope[Page[dict]], tags=['习题自测'])
    def exercise_history(book_id: str, request: Request, ctx: Context, page: PageNumber = 1, page_size: PageSize = 20):
        return envelope(request, app.state.self_tests.history(ctx[0], book_id, page, page_size))

    @router.get('/books/{book_id}/exercise-statistics', response_model=Envelope[dict], tags=['习题自测'])
    def exercise_statistics(book_id: str, request: Request, ctx: Context):
        return envelope(request, app.state.self_tests.stats(ctx[0], book_id))

    app.include_router(router)

    def login_page(message=''):
        csrf = secrets.token_urlsafe(32)
        page = (ROOT / 'static/login/index.html').read_text(encoding='utf-8')
        response = HTMLResponse(page.replace('{{CSRF}}', html.escape(csrf, quote=True)).replace('{{MESSAGE}}', html.escape(message)))
        response.set_cookie('literary_csrf', csrf, httponly=True, samesite='strict', max_age=600)
        return response

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    @app.get('/login', response_class=HTMLResponse, include_in_schema=False)
    def browser_login():
        return login_page()

    @app.post('/login', include_in_schema=False)
    def browser_login_submit(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...)):
        if not request.cookies.get('literary_csrf') or not secrets.compare_digest(request.cookies['literary_csrf'], csrf):
            raise Error(403, 'FORBIDDEN', '登录表单已过期，请重新打开登录页')
        try:
            data = app.state.auth.service.login(username, password)
        except AuthError:
            return login_page('用户名或密码错误')
        response = RedirectResponse(os.getenv('LITERARY_APP_URL', 'http://localhost:8501'), status_code=303)
        response.set_cookie(COOKIE, data['refresh_token'], httponly=True, samesite='strict', max_age=REFRESH_TTL)
        response.delete_cookie('literary_csrf')
        return response

    @app.get('/logout', response_class=HTMLResponse, include_in_schema=False)
    def browser_logout():
        csrf = secrets.token_urlsafe(32)
        response = HTMLResponse(f'<meta charset="utf-8"><h2>退出伴读精灵</h2><form method="post"><input type="hidden" name="csrf" value="{csrf}"><button>确认退出并清除浏览器凭证</button></form>')
        response.set_cookie('literary_csrf', csrf, httponly=True, samesite='strict', max_age=600)
        return response

    @app.post('/logout', include_in_schema=False)
    def browser_logout_submit(request: Request, csrf: str = Form(...)):
        if not request.cookies.get('literary_csrf') or not secrets.compare_digest(request.cookies['literary_csrf'], csrf):
            raise Error(403, 'FORBIDDEN', '退出表单已过期')
        token = request.cookies.get(COOKIE)
        if token:
            app.state.auth.service.logout(token)
        response = RedirectResponse('/login', status_code=303)
        response.delete_cookie(COOKIE)
        response.delete_cookie('literary_csrf')
        return response

    from fastapi.staticfiles import StaticFiles
    app.mount('/static/login', StaticFiles(directory=ROOT / 'static/login'), name='login-assets')
    return app
