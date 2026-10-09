"""Streamlit AppTest -> APIClient -> real FastAPI/SQLite; no provider calls."""
from unittest.mock import patch
import requests
import pytest
from streamlit.testing.v1 import AppTest
from api_client import APIClient, APIError
from test_fastapi_service import env, setup_chat, login, ROOT


class Bridge:
    def __init__(self, client):
        self.client = client

    def request(self, method, url, **kwargs):
        kwargs.pop('timeout', None)
        return self.client.request(method, url, **kwargs)


def element(items, label):
    return next(x for x in items if x.label == label)


def test_frontend_chat_history_pages_and_logout(env):
    c, app, adapter, _ = env
    h, bid, _, sid = setup_chat(c)
    headers, token = login(c)
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('红楼梦', bid))
    def factory(access_token='', refresh_token=''):
        return APIClient(access_token, refresh_token, transport=Bridge(c))
    with patch('frontend.APIClient', side_effect=factory):
        page = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
        page.session_state.api_access = token['access_token']
        page.session_state.api_refresh = token['refresh_token']
        page.session_state.api_book = bid
        page.run()
        assert not page.exception
        assert page.chat_input
        page.chat_input[0].set_value('人物是谁？').run()
        assert not page.exception
        assert adapter.calls == 1
        assert any('依据原著的测试回答' in x.value for x in page.markdown)
        page.run()
        assert adapter.calls == 1
        element(page.radio, '选择页面').set_value('关系图谱').run()
        assert not page.exception
        assert any('贾宝玉' in x.label for x in page.expander)
        element(page.radio, '选择页面').set_value('做题').run()
        assert not page.exception
        element(page.multiselect, '选择章节（可多选）').set_value(['第一回', '第三回']).run()
        element(page.button, '开始自测').click().run()
        assert not page.exception
        answer_radios = [radio for radio in page.radio if radio.label == '选择答案']
        assert len(answer_radios) == 3
        element(page.button, '提交全部答案').click().run()
        assert any('请先选择答案' in x.value for x in page.warning)
        answer_radios = [radio for radio in page.radio if radio.label == '选择答案']
        for radio, answer in zip(answer_radios, [2, 3, 1]):
            radio.set_value(answer)
        element(page.button, '提交全部答案').click().run()
        assert not page.exception
        assert any('正确 3 / 3' in x.value for x in page.success)
        assert any('原著出处' in x.value for x in page.markdown)
        page.session_state.app_area = 'settings'
        page.run()
        element(page.button, '退出登录').click().run()
        assert not page.exception
        assert any('http-equiv="refresh"' in x.value and '/login' in x.value for x in page.markdown)
        assert page.session_state.api_access == ''


def test_frontend_login_and_api_unavailable(env):
    c, _, _, _ = env
    def factory(access_token='', refresh_token=''):
        return APIClient(access_token, refresh_token, transport=Bridge(c))
    with patch('frontend.APIClient', side_effect=factory):
        page = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        assert not page.exception
        assert not page.text_input
        assert not page.title
        assert any('http-equiv="refresh"' in x.value and '/login' in x.value for x in page.markdown)
        _, tokens = login(c)
        page.session_state.api_access = tokens['access_token']
        page.session_state.api_refresh = tokens['refresh_token']
        page.run()
        assert not page.exception
        assert any('暂无书籍' in x.value for x in page.info)
        with patch.object(APIClient, 'request', side_effect=APIError('API_UNAVAILABLE', '无法连接 API')):
            page.run()
            assert not page.exception
            assert any('无法连接 API' in x.value for x in page.error)


def test_frontend_request_retry_preserves_key(env):
    c, app, adapter, _ = env
    _, bid, _, sid = setup_chat(c)
    _, token = login(c)
    adapter.error = 'ReadTimeout'
    def factory(access_token='', refresh_token=''):
        return APIClient(access_token, refresh_token, transport=Bridge(c))
    with patch('frontend.APIClient', side_effect=factory):
        page = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
        page.session_state.api_access = token['access_token']
        page.session_state.api_refresh = token['refresh_token']
        page.session_state.api_book = bid
        page.run()
        page.chat_input[0].set_value('人物是谁？').run()
        assert not page.exception
        key = page.session_state.api_pending_question['key']
        page.run()
        element(page.button, '使用原请求重试').click().run()
        assert not page.exception
        assert page.session_state.api_pending_question['key'] == key
        assert adapter.calls == 1


def test_client_refresh_once_and_failed_refresh_is_bounded(env):
    c, _, _, _ = env
    _, token = login(c)
    client = APIClient('bad-token', token['refresh_token'], Bridge(c))
    assert client.request('GET', '/api/auth/me')['username'] == 'demo'
    assert client.access_token != 'bad-token'
    client.access_token = client.refresh_token = 'bad-token'
    with pytest.raises(APIError) as error:
        client.request('GET', '/api/auth/me')
    assert error.value.status == 401


def test_client_timeout_does_not_retry_post():
    class TimeoutTransport:
        calls = 0
        def request(self, *args, **kwargs):
            self.calls += 1
            raise requests.Timeout()
    transport = TimeoutTransport()
    client = APIClient(transport=transport)
    with pytest.raises(APIError) as error:
        client.request('POST', '/api/books', json={'name': 'x'}, key='same-key')
    assert error.value.code == 'CLIENT_TIMEOUT'
    assert transport.calls == 1


def test_frontend_create_book_session_and_refresh(env):
    c, _, _, _ = env
    _, token = login(c)
    def factory(access_token='', refresh_token=''):
        return APIClient(access_token, refresh_token, transport=Bridge(c))
    with patch('frontend.APIClient', side_effect=factory):
        page = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
        page.session_state.api_access = token['access_token']
        page.session_state.api_refresh = token['refresh_token']
        page.run()
        element(page.text_input, '书籍名称').set_value('界面测试书')
        element(page.button, '创建书籍').click().run()
        assert not page.exception
        page.run()
        assert not page.exception
        assert element(page.button, '进入阅读空间')
        page.session_state.app_area = 'reader'
        page.run()
        element(page.button, '＋').click().run()
        assert not page.exception
        assert page.chat_input
        headers = {'Authorization': 'Bearer '+token['access_token']}
        sessions = c.get(f'/api/books/{page.session_state.api_book}/sessions', headers=headers).json()['data']['items']
        sid = sessions[0]['id']
        rename = {'action': 'rename', 'session_id': sid, 'name': '界面会话', 'event_id': 'rename-1'}
        with patch('frontend.session_context_menu', return_value=rename):
            page.run()
        assert not page.exception
        sessions = c.get(f'/api/books/{page.session_state.api_book}/sessions', headers=headers).json()['data']['items']
        assert sessions[0]['name'] == '界面会话'
        assert c.get('/api/books', headers=headers).json()['data']['total'] == 1
