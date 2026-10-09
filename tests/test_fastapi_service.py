"""Real ASGI, SQLite, multipart and encryption; only inference/indexing are faked."""
import json
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from api import create_app
from backend.database import dump, now
from backend.runtime import ROOT
from chat_backend import ChatSettings
from migrate_service import migrate


class FakeRag:
    def __init__(self, root):
        self.root = root
        self.files = {}
        self.calls = 0
        self.fail_index = self.fail_cleanup = False
        self.error = None
        self.rejected = False
        self.entered = self.release = None
        self.histories = []

    def ready(self):
        pass

    def index(self, bid, fid, name, text):
        self.files[(bid, fid)] = text
        if self.fail_index:
            raise RuntimeError('partial indexing failure')
        return 2

    def remove_file(self, bid, fid):
        if self.fail_cleanup:
            raise RuntimeError('cleanup unavailable')
        self.files.pop((bid, fid), None)

    def remove_book(self, bid):
        if self.fail_cleanup:
            raise RuntimeError('cleanup unavailable')
        self.files = {k: v for k, v in self.files.items() if k[0] != bid}

    def answer(self, bid, question, history, settings):
        self.calls += 1
        self.histories.append(history)
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.error:
            return {'error': self.error}
        return {'answer': '原著没有依据' if self.rejected else '依据原著的测试回答', 'sources': [{'text': '原文片段', 'metadata': {'file_id': 'test', 'file_name': 'original.txt', 'chapter': '第一回', 'path': 'SECRET_PATH'}}], 'min_distance': 0.2, 'rejected': self.rejected}


@pytest.fixture
def env(tmp_path):
    root = tmp_path / 'project'
    data = root / 'data'
    data.mkdir(parents=True)
    for path in (ROOT / 'data').glob('*_*.json'):
        if path.name.startswith(('characters_', 'exercises_')):
            shutil.copy2(path, data / path.name)
    adapter = FakeRag(root)
    app = create_app(data, adapter, ChatSettings('ollama', 'fake-model', 'http://localhost:11434'))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app, adapter, root


def login(client, admin=False):
    r = client.post('/api/auth/login', json={'username': 'admin' if admin else 'demo', 'password': 'Admin@123456' if admin else 'Demo@123456'})
    assert r.status_code == 200, r.text
    token = r.json()['data']
    return {'Authorization': 'Bearer ' + token['access_token']}, token


def book(client, headers, key='book1'):
    r = client.post('/api/books', headers=dict(headers, **{'Idempotency-Key': key}), json={'name': '测试书籍'})
    assert r.status_code == 201, r.text
    return r.json()['data']['id']


def setup_chat(client):
    headers, _ = login(client)
    bid = book(client, headers)
    r = client.post(f'/api/books/{bid}/files', headers=dict(headers, **{'Idempotency-Key': 'file1'}), files={'file': ('original.txt', '第一回 原文内容。'.encode())})
    assert r.status_code == 201, r.text
    fid = r.json()['data']['id']
    r = client.post(f'/api/books/{bid}/sessions', headers=dict(headers, **{'Idempotency-Key': 'session1'}), json={})
    assert r.status_code == 201, r.text
    return headers, bid, fid, r.json()['data']['id']


def ask(client, headers, sid, key='q1', question='人物是谁？'):
    return client.post(f'/api/sessions/{sid}/questions', headers=dict(headers, **{'Idempotency-Key': key}), json={'question': question})


def test_health_schema_errors_and_auth(env):
    c, app, _, _ = env
    assert c.get('/health/live').status_code == 200
    assert c.get('/health/ready').json()['data']['ready']
    assert c.get('/docs').status_code == 200
    schema = c.get('/openapi.json').json()
    assert schema['components']['securitySchemes']['HTTPBearer']['scheme'] == 'bearer'
    assert len(schema['paths']) >= 25
    assert c.get('/api/books').status_code == 401
    bad = c.post('/api/auth/login', json={'username': [], 'password': 'SECRET_PASSWORD'})
    assert bad.status_code == 422
    assert 'SECRET_PASSWORD' not in bad.text
    assert bad.json()['request_id'] == bad.headers['X-Request-ID']
    assert c.get('/unknown').json()['code'] == 'RESOURCE_NOT_FOUND'
    headers, token = login(c)
    refreshed = c.post('/api/auth/refresh', json={'refresh_token': token['refresh_token']}).json()['data']
    assert refreshed['refresh_token'] == token['refresh_token']
    assert c.get('/api/auth/me', headers=headers).status_code == 200
    assert c.post('/api/auth/logout', json={'refresh_token': token['refresh_token']}).status_code == 200
    assert c.get('/api/auth/me', headers=headers).status_code == 401
    assert c.post('/api/auth/logout', json={'refresh_token': token['refresh_token']}).status_code == 200


def test_browser_csrf_login_assets_logout(env):
    import re
    c, _, _, _ = env
    page = c.get('/login')
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert c.post('/login', data={'username': 'demo', 'password': 'Demo@123456', 'csrf': 'bad'}).status_code == 403
    r = c.post('/login', data={'username': 'demo', 'password': 'Demo@123456', 'csrf': csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert 'HttpOnly' in r.headers['set-cookie']
    assert c.get('/static/login/style.css').status_code == 200
    assert c.get('/static/login/book-illustration.png').status_code == 200
    page = c.get('/logout')
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert c.post('/logout', data={'csrf': csrf}, follow_redirects=False).status_code == 303
    assert 'literary_refresh' not in c.cookies


def test_book_idempotency_validation_pagination(env):
    c, _, _, _ = env
    h, _ = login(c)
    bid = book(c, h)
    assert book(c, h) == bid
    replay = c.post('/api/books', headers=dict(h, **{'Idempotency-Key': 'book1'}), json={'name': '测试书籍'})
    assert replay.headers['Idempotency-Replayed'] == 'true'
    assert c.post('/api/books', headers=dict(h, **{'Idempotency-Key': 'book1'}), json={'name': 'different'}).status_code == 409
    for name in ('', '   ', 'x'*101):
        assert c.post('/api/books', headers=dict(h, **{'Idempotency-Key': 'new'}), json={'name': name}).status_code == 422
    assert c.post('/api/books', headers=h, json={'name': 'x'}).status_code == 422
    assert c.get('/api/books?page_size=101', headers=h).status_code == 422
    assert c.get('/api/books?q=nothing', headers=h).json()['data']['items'] == []
    assert c.patch(f'/api/books/{bid}', headers=h, json={'name': '新名称'}).json()['data']['name'] == '新名称'


def test_book_metadata_and_cover(env):
    c, _, _, _ = env
    h, _ = login(c)
    bid = book(c, h)
    metadata = {
        'name': '西游记',
        'author': '吴承恩',
        'category': '中国古典',
        'description': '神魔冒险与成长。',
    }
    updated = c.patch(f'/api/books/{bid}', headers=h, json=metadata)
    assert updated.status_code == 200, updated.text
    assert {key: updated.json()['data'][key] for key in metadata} == metadata
    assert updated.json()['data']['has_cover'] is False

    raw = b'\x89PNG\r\n\x1a\n' + b'test-cover'
    uploaded = c.put(f'/api/books/{bid}/cover', headers=h, files={'file': ('cover.png', raw, 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()['data']['has_cover'] is True
    cover = c.get(f'/api/books/{bid}/cover', headers=h)
    assert cover.status_code == 200
    assert cover.headers['content-type'] == 'image/png'
    assert cover.content == raw
    assert c.put(f'/api/books/{bid}/cover', headers=h, files={'file': ('cover.txt', b'bad', 'text/plain')}).status_code == 415
    assert c.patch(f'/api/books/{bid}', headers=h, json={}).status_code == 422


def test_private_resources_and_shared_readonly(env):
    c, app, _, _ = env
    h, bid, fid, sid = setup_chat(c)
    admin, _ = login(c, True)
    for path in (f'/api/books/{bid}', f'/api/books/{bid}/sessions', f'/api/sessions/{sid}/messages'):
        assert c.get(path, headers=admin).status_code == 404
    assert ask(c, admin, sid).status_code == 404
    assert c.delete(f'/api/books/{bid}/files/{fid}', headers=admin).status_code == 404
    assert c.get('/api/books', headers=admin).json()['data']['items'] == []
    shared = book(c, admin, 'shared')
    with app.state.database.tx() as db:
        db.execute("UPDATE books SET visibility='shared' WHERE id=?", (shared,))
    assert c.get(f'/api/books/{shared}', headers=h).status_code == 200
    assert c.patch(f'/api/books/{shared}', headers=h, json={'name': 'illegal'}).status_code == 403
    assert c.delete(f'/api/books/{shared}', headers=h).status_code == 403


@pytest.mark.parametrize('name,content,status', [('x.exe', b'abc', 415), ('x.txt', b'', 400), ('x.txt', b'   ', 400), ('x.pdf', b'fake pdf', 415), ('x.docx', b'fake zip', 415), ('../x.txt', b'abc', 422), ('x.txt', b'%PDF- fake', 415)])
def test_invalid_upload(env, name, content, status):
    c, _, _, _ = env
    h, _ = login(c)
    bid = book(c, h)
    r = c.post(f'/api/books/{bid}/files', headers=dict(h, **{'Idempotency-Key': 'f'}), files={'file': (name, content)})
    assert r.status_code == status, r.text


def test_upload_size_and_content_dedup(env):
    c, _, adapter, _ = env
    h, bid, fid, sid = setup_chat(c)
    r = c.post(f'/api/books/{bid}/files', headers=dict(h, **{'Idempotency-Key': 'other-upload'}), files={'file': ('renamed.txt', '第一回 原文内容。'.encode())})
    assert r.status_code == 200
    assert r.json()['data']['id'] == fid
    assert len(adapter.files) == 1
    r = c.post(f'/api/books/{bid}/files', headers=dict(h, **{'Idempotency-Key': 'huge'}), files={'file': ('huge.txt', b'a'*(20*1024*1024+1))})
    assert r.status_code == 413


def test_conversation_and_preference_crud(env):
    c, _, _, _ = env
    h, bid, _, sid = setup_chat(c)
    assert c.patch(f'/api/sessions/{sid}', headers=h, json={'name': '改名'}).json()['data']['name'] == '改名'
    pref = {'last_book_id': bid, 'active_session_by_book': {bid: sid}}
    assert c.put('/api/me/preferences', headers=h, json=pref).json()['data'] == pref
    admin, _ = login(c, True)
    assert c.get('/api/me/preferences', headers=admin).json()['data']['last_book_id'] is None
    other = book(c, h, 'book2')
    assert c.put('/api/me/preferences', headers=h, json={'last_book_id': other, 'active_session_by_book': {other: sid}}).status_code == 422
    assert ask(c, h, sid).status_code == 201
    assert c.delete(f'/api/sessions/{sid}/messages', headers=h).json()['data']['cleared']
    assert c.get(f'/api/sessions/{sid}/messages', headers=h).json()['data']['total'] == 0
    assert ask(c, h, sid).status_code == 410
    assert c.delete(f'/api/sessions/{sid}', headers=h).status_code == 200
    assert c.delete(f'/api/sessions/{sid}', headers=h).status_code == 200
    assert c.get('/api/me/preferences', headers=h).json()['data']['active_session_by_book'] == {}


def test_question_saved_once_with_server_history(env):
    c, _, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    first = ask(c, h, sid)
    assert first.status_code == 201, first.text
    turn = first.json()['data']
    assert 'SECRET_PATH' not in first.text
    assert turn['turn_id'] > 0
    assert ask(c, h, sid).json()['data'] == turn
    assert adapter.calls == 1
    assert ask(c, h, sid, question='不同问题').status_code == 409
    assert ask(c, h, sid, key='q2', question='下一问题').status_code == 201
    assert len(adapter.histories[1]) == 1
    assert c.get(f'/api/sessions/{sid}/messages', headers=h).json()['data']['total'] == 2
    assert c.post(f'/api/sessions/{sid}/questions', headers=dict(h, **{'Idempotency-Key': 'q3'}), json={'question': 'x', 'history': []}).status_code == 422


def test_relationship_graph_tool_result_is_saved_in_chat(env):
    c, app, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('西游记', bid))

    response = ask(c, h, sid, question='给我西游记人物关系图')
    assert response.status_code == 201, response.text
    turn = response.json()['data']
    assert adapter.calls == 0
    assert turn['sources'] == []
    assert turn['tool_calls'][0]['name'] == 'show_relationship_graph'
    assert turn['tool_calls'][0]['result']['format'] == 'mermaid'
    assert '孙悟空' in turn['tool_calls'][0]['result']['code']
    saved = c.get(f'/api/sessions/{sid}/messages', headers=h).json()['data']['items'][0]
    assert saved['tool_calls'] == turn['tool_calls']


def test_relationship_graph_tool_can_focus_on_one_character(env):
    c, app, _, _ = env
    h, bid, _, sid = setup_chat(c)
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('西游记', bid))

    turn = ask(c, h, sid, question='显示孙悟空的人物关系图').json()['data']
    call = turn['tool_calls'][0]
    assert call['arguments'] == {'character_name': '孙悟空'}
    assert '孙悟空' in call['result']['code']
    assert '贾宝玉' not in call['result']['code']


def test_character_and_event_lookup_tools_return_dataset_json(env):
    c, app, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('西游记', bid))

    character = ask(c, h, sid, key='character-tool', question='孙悟空的人物信息和身份').json()['data']
    character_call = character['tool_calls'][0]
    assert character_call['name'] == 'lookup_characters'
    assert character_call['result']['items'][0]['name'] == '孙悟空'
    assert character_call['result']['items'][0]['identity'] == '齐天大圣、斗战胜佛'

    event = ask(c, h, sid, key='event-tool', question='第二回有哪些事件').json()['data']
    event_call = event['tool_calls'][0]
    assert event_call['name'] == 'lookup_events'
    assert event_call['arguments']['chapter'] == '第2回'
    assert [row['name'] for row in event_call['result']['items']] == ['大闹龙宫']
    assert adapter.calls == 0


@pytest.mark.parametrize('error,status', [('ReadTimeout', 504), ('RuntimeError', 502)])
def test_failed_question_not_saved_or_recalled(env, error, status):
    c, _, adapter, _ = env
    h, _, _, sid = setup_chat(c)
    adapter.error = error
    assert ask(c, h, sid).status_code == status
    assert ask(c, h, sid).status_code == status
    assert adapter.calls == 1
    assert c.get(f'/api/sessions/{sid}/messages', headers=h).json()['data']['total'] == 0


def test_rejected_answer_and_unready_book(env):
    c, _, adapter, _ = env
    h, _, fid, sid = setup_chat(c)
    adapter.rejected = True
    assert ask(c, h, sid).json()['data']['rejected']
    h2, _ = login(c)
    bid2 = book(c, h2, 'empty')
    sid2 = c.post(f'/api/books/{bid2}/sessions', headers=dict(h2, **{'Idempotency-Key': 's2'}), json={}).json()['data']['id']
    assert ask(c, h2, sid2).status_code == 409


def test_concurrent_question_and_delete_are_rejected(env):
    c, _, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    adapter.entered, adapter.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor() as pool:
        task = pool.submit(ask, c, h, sid)
        assert adapter.entered.wait(5)
        try:
            assert ask(c, h, sid).status_code == 409
            assert ask(c, h, sid, key='another').status_code == 409
            assert c.delete(f'/api/sessions/{sid}/messages', headers=h).status_code == 409
            assert c.delete(f'/api/books/{bid}', headers=h).status_code == 409
        finally:
            adapter.release.set()
        assert task.result().status_code == 201
    assert adapter.calls == 1


def test_save_pending_retries_without_model_call(env, monkeypatch):
    c, app, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    original = app.state.database.save_turn
    def fail(*args):
        raise sqlite3.OperationalError('simulated disk failure')
    monkeypatch.setattr(app.state.database, 'save_turn', fail)
    r = ask(c, h, sid)
    assert r.status_code == 503, r.text
    assert r.json()['code'] == 'SAVE_PENDING'
    assert c.delete(f'/api/sessions/{sid}/messages', headers=h).status_code == 409
    assert c.delete(f'/api/books/{bid}', headers=h).status_code == 409
    monkeypatch.setattr(app.state.database, 'save_turn', original)
    assert ask(c, h, sid).status_code == 201
    assert adapter.calls == 1
    assert c.get(f'/api/sessions/{sid}/messages', headers=h).json()['data']['total'] == 1


def test_failed_upload_cleanup_and_delete_recovery(env):
    c, app, adapter, _ = env
    h, _ = login(c)
    bid = book(c, h)
    adapter.fail_index = adapter.fail_cleanup = True
    r = c.post(f'/api/books/{bid}/files', headers=dict(h, **{'Idempotency-Key': 'f1'}), files={'file': ('x.txt', b'original text')})
    assert r.status_code == 503
    assert c.get('/health/ready').status_code == 503
    adapter.fail_index = adapter.fail_cleanup = False
    app.state.books.recover()
    assert c.get(f'/api/books/{bid}', headers=h).json()['data']['files'] == []
    assert not adapter.files
    r = c.post(f'/api/books/{bid}/files', headers=dict(h, **{'Idempotency-Key': 'f2'}), files={'file': ('x.txt', b'original text')})
    fid = r.json()['data']['id']
    adapter.fail_cleanup = True
    assert c.delete(f'/api/books/{bid}/files/{fid}', headers=h).status_code == 503
    adapter.fail_cleanup = False
    app.state.books.recover()
    assert c.delete(f'/api/books/{bid}/files/{fid}', headers=h).status_code == 200
    assert c.delete(f'/api/books/{bid}', headers=h).status_code == 200
    assert c.delete(f'/api/books/{bid}', headers=h).status_code == 200


def test_book_delete_cascades_and_is_private(env):
    c, _, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    ask(c, h, sid)
    c.put('/api/me/preferences', headers=h, json={'last_book_id': bid, 'active_session_by_book': {bid: sid}})
    assert c.delete(f'/api/books/{bid}', headers=h).status_code == 200
    assert not adapter.files
    assert c.get(f'/api/sessions/{sid}/messages', headers=h).status_code == 404
    assert c.get('/api/me/preferences', headers=h).json()['data'] == {'last_book_id': None, 'active_session_by_book': {}}
    admin, _ = login(c, True)
    assert c.delete(f'/api/books/{bid}', headers=admin).status_code == 404


def test_business_mapping_survives_rename_and_validation(env):
    c, app, _, _ = env
    h, _ = login(c)
    bid = book(c, h)
    assert c.get(f'/api/books/{bid}/exercises', headers=h).status_code == 409
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('红楼梦', bid))
    prefix = f'/api/books/{bid}'
    c.patch(prefix, headers=h, json={'name': '重命名后的书'})
    chars = c.get(prefix + '/characters', headers=h).json()['data']
    assert chars['total'] > 0
    cid = chars['items'][0]['id']
    assert c.get(prefix + f'/characters/{cid}', headers=h).status_code == 200
    assert c.get(prefix + f'/characters/{cid}/relations', headers=h).json()['data']['items']
    assert c.get(prefix + '/families', headers=h).status_code == 200
    assert c.get(prefix + '/relationship-graph?scope=character', headers=h).status_code == 422
    assert c.get(prefix + '/relationship-graph?scope=wrong', headers=h).status_code == 422
    assert c.get(prefix + '/relationship-graph', headers=h).json()['data']['format'] == 'mermaid'
    assert c.get(prefix + '/events', headers=h).status_code == 200
    assert c.get(prefix + '/characters/unknown', headers=h).status_code == 404
    exercises = c.get(prefix + '/exercises?difficulty=easy', headers=h).json()['data']
    assert exercises['total'] > 0
    assert c.get(prefix + '/exercises?difficulty=illegal', headers=h).status_code == 422
    eid = exercises['items'][0]['id']
    assert c.get(prefix + f'/exercises/{eid}', headers=h).status_code == 200
    assert c.get(prefix + '/exercises/unknown', headers=h).status_code == 404
    assert c.get(prefix + '/exercise-chapters', headers=h).json()['data']['items']


def test_model_settings_secret_isolation_and_logout(env):
    c, app, _, _ = env
    h, token = login(c)
    assert c.get('/api/auth/model-settings', headers=h).json()['data']['source'] == 'default'
    settings = {'mode': 'api', 'model': 'test', 'base_url': 'https://provider.test', 'api_key': 'SECRET_TEST_KEY'}
    r = c.put('/api/auth/model-settings', headers=h, json=settings)
    assert r.status_code == 200, r.text
    assert 'SECRET_TEST_KEY' not in r.text
    second, _ = login(c)
    assert c.get('/api/auth/model-settings', headers=second).json()['data']['source'] == 'default'
    assert c.put('/api/auth/model-settings', headers=second, json={k: v for k, v in settings.items() if k != 'api_key'}).status_code == 422
    assert c.delete('/api/auth/model-settings', headers=h).status_code == 200
    c.put('/api/auth/model-settings', headers=h, json=settings)
    c.post('/api/auth/logout', json={'refresh_token': token['refresh_token']})
    with app.state.auth.service.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM login_model_settings').fetchone()[0] == 0


def test_restart_idempotency_and_unknown_result(tmp_path):
    adapter = FakeRag(tmp_path)
    data = tmp_path / 'data'
    settings = ChatSettings('ollama', 'fake', 'http://localhost:11434')
    app = create_app(data, adapter, settings)
    with TestClient(app) as c:
        h, bid, fid, sid = setup_chat(c)
        first = ask(c, h, sid).json()['data']
        with app.state.database.tx() as db:
            app.state.database.reserve(db, {'id': 1}, f'question:{sid}', 'interrupted', {'question': 'interrupted'})
    app2 = create_app(data, adapter, settings)
    with TestClient(app2) as c:
        assert ask(c, h, sid).json()['data'] == first
        assert ask(c, h, sid, key='interrupted', question='interrupted').json()['code'] == 'RESULT_UNKNOWN'
    assert adapter.calls == 1


def test_migration_preserves_ids_backups_and_runs_once(tmp_path):
    root = tmp_path / 'legacy'
    data = root / 'data'
    data.mkdir(parents=True)
    books = [{'id': 'short-id', 'name': '红楼梦', 'created_at': '2026-06-24T12:00:00', 'files': []}]
    (data / 'books.json').write_text(dump(books), encoding='utf-8')
    (root / 'chat_history_cache.json').write_text(dump({'红楼梦': [{'question': 'q', 'answer': 'a'}], 'unknown': [{'question': 'q', 'answer': 'a'}]}), encoding='utf-8')
    shutil.copy2(ROOT / 'data/characters_红楼梦.json', data / 'characters_红楼梦.json')
    result = migrate(root, owner='demo')
    assert result['books'] == 1 and result['turns'] == 1
    assert result['unmatched_history'] == ['unknown']
    assert (Path(result['backup']) / 'books.json').exists()
    assert migrate(root, owner='demo')['already_migrated']
    assert json.loads((data / 'books.json').read_text(encoding='utf-8')) == books
    with sqlite3.connect(data / 'service.sqlite3') as db:
        assert db.execute('SELECT id,dataset FROM books').fetchone() == ('short-id', '红楼梦')


def test_migration_counts_real_index_and_preserves_unindexed_metadata(tmp_path):
    root = tmp_path / 'legacy'
    data = root / 'data'
    data.mkdir(parents=True)
    files = [{'id': 'indexed', 'name': 'one.txt', 'chunk_count': 0}, {'id': 'unindexed', 'name': 'two.txt', 'chunk_count': 0}]
    (data / 'books.json').write_text(dump([{'id': 'book', 'name': 'book', 'files': files}]), encoding='utf-8')
    index = root / 'chroma_db/book_book'
    index.mkdir(parents=True)
    with sqlite3.connect(index / 'chroma.sqlite3') as db:
        db.execute('CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT)')
        db.executemany('INSERT INTO embedding_metadata VALUES (?,?,?)', [(1, 'file_id', 'indexed'), (2, 'file_id', 'indexed')])
    report = migrate(root, owner='demo')
    assert report['index_reconciliation'] == {'files': 2, 'chunks': 2, 'unindexed_files': 1}
    app = create_app(data, FakeRag(root), ChatSettings('ollama', 'test', 'http://localhost:11434'))
    with TestClient(app) as c:
        h, _ = login(c)
        book = c.get('/api/books/book', headers=h).json()['data']
        assert book['chunk_count'] == 2 and len(book['files']) == 2
        assert {x['status'] for x in book['files']} == {'ready', 'legacy_unindexed'}
