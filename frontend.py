"""Streamlit presentation only. All business reads/writes use APIClient."""
import hashlib
import html
import uuid
import base64
from pathlib import Path
from urllib.parse import quote
import streamlit as st
import streamlit.components.v1 as components
from api_client import APIClient, APIError


SESSION_MENU_PATH = Path(__file__).parent / 'static' / 'session_menu'
session_context_menu = components.declare_component('session_context_menu', path=str(SESSION_MENU_PATH))


BOOK_PRESENTATION = {
    '西游记': ('吴承恩', '中国古典', '一场从大唐出发的漫长修行。在神魔奇遇中读懂勇气、秩序与成长。'),
    '红楼梦': ('曹雪芹', '中国古典', '在大观园的盛衰与群像之中，阅读家族、青春与命运的交织。'),
    '三体': ('刘慈欣', '科幻文学', '当人类文明被置于宇宙尺度，科学、信念与生存选择共同构成一场思想实验。'),
    '海底两万里': ('儒勒·凡尔纳', '外国文学', '跟随鹦鹉螺号潜入海底，在未知世界中探索科学、自由与选择。'),
    '绿山墙的安妮': ('露西·莫德·蒙哥马利', '外国文学', '一个富有想象力的女孩，在爱与成长中把陌生之地变成真正的家。'),
    '平凡的世界': ('路遥', '中国现当代', '在时代变迁与日常生活中，看见普通人的坚韧、尊严与选择。'),
}


def apply_theme():
    css = (Path(__file__).parent / 'static' / 'app' / 'style.css').read_text(encoding='utf-8')
    st.markdown('<style>' + css + '</style>', unsafe_allow_html=True)


def brand():
    st.markdown('<div class="reading-brand"><span class="reading-brand__mark">书</span><span>伴读精灵</span></div>', unsafe_allow_html=True)


def presentation(book):
    fallback = BOOK_PRESENTATION.get(book['name'], ('作者待补充', '未分类', '简介待补充。'))
    category = book.get('category')
    return {
        'author': book.get('author') or fallback[0],
        'category': fallback[1] if not category or category == '未分类' else category,
        'description': book.get('description') or fallback[2],
    }


def segment(value):
    return quote(str(value), safe='')


def key_for(action):
    keys = st.session_state.setdefault('api_operation_keys', {})
    return keys.setdefault(action, str(uuid.uuid4()))


def completed(action):
    st.session_state.setdefault('api_operation_keys', {}).pop(action, None)


def show_error(exc):
    st.error(f'{exc}（{exc.code}）')
    if exc.request_id:
        st.caption('请求编号：' + exc.request_id)


def require_client():
    client = APIClient(st.session_state.get('api_access', ''), st.session_state.get('api_refresh', ''))
    context = getattr(st, 'context', None)
    cookie = getattr(context, 'cookies', {}).get('literary_refresh', '')
    if not isinstance(cookie, str):
        cookie = ''
    if cookie and cookie != st.session_state.get('api_logged_out_cookie') and not client.refresh_token:
        client.refresh_token = cookie
    if client.refresh_token:
        try:
            if not client.access_token:
                client.restore()
            user = client.request('GET', '/api/auth/me')
            st.session_state.api_access, st.session_state.api_refresh = client.access_token, client.refresh_token
            return client, user
        except APIError as exc:
            if exc.status != 401:
                show_error(exc)
                st.stop()
            st.session_state.pop('api_access', None)
            st.session_state.pop('api_refresh', None)
            st.session_state.api_logged_out_cookie = cookie
    login_url = html.escape(client.public_url + '/login', quote=True)
    st.markdown(f'<meta http-equiv="refresh" content="0;url={login_url}">', unsafe_allow_html=True)
    st.stop()


def model_settings(client, host=st):
    with host.expander('回答模型', expanded=True):
        saved = client.request('GET', '/api/auth/model-settings')
        st.caption('当前使用：' + ('本次登录配置' if saved['source'] == 'login' else '项目默认配置'))
        with st.form('api_model'):
            mode = st.selectbox('回答方式', ['api', 'ollama'], index=0 if saved['mode'] == 'api' else 1, key='api_model_mode')
            model = st.text_input('模型 ID', value=saved['model'], key='api_model_id')
            url = st.text_input('模型 API 基础网址', value=saved['base_url'], key='api_model_url')
            token = st.text_input('AI API 密钥', type='password', key='api_model_key', help='首次远程配置或更换地址时必填；留空仅保留已保存的同地址密钥。')
            if st.form_submit_button('保存本次登录的配置'):
                body = {'mode': mode, 'model': model, 'base_url': url}
                if token:
                    body['api_key'] = token
                client.request('PUT', '/api/auth/model-settings', json=body)
                st.rerun()
        if st.button('恢复项目默认配置'):
            client.request('DELETE', '/api/auth/model-settings')
            st.rerun()
        st.caption('嵌入模型由后端管理；退出登录后清除本次模型配置。')


def bookshelf(client):
    with st.sidebar:
        st.subheader('书架')
        query = st.text_input('搜索书籍', max_chars=100, key='api_book_search')
        books = client.all('/api/books', q=query)
        with st.expander('新建书籍'):
            with st.form('api_new_book'):
                name = st.text_input('书籍名称', max_chars=100, key='api_book_name')
                if st.form_submit_button('创建书籍'):
                    action = 'create-book:' + name
                    book = client.request('POST', '/api/books', json={'name': name}, key=key_for(action))
                    completed(action)
                    st.session_state.api_book = book['id']
                    st.session_state.pop('book_picker', None)
                    st.rerun()
        if not books:
            st.info('暂无书籍。首次使用可迁移旧数据，或新建书籍并上传原著。')
            return None
        ids, names = [b['id'] for b in books], {b['id']: b['name'] for b in books}
        if 'api_preferences' not in st.session_state:
            st.session_state.api_preferences = client.request('GET', '/api/me/preferences')
        previous = st.session_state.get('api_book', st.session_state.api_preferences['last_book_id'])
        if st.session_state.get('book_picker') not in ids:
            st.session_state.book_picker = previous if previous in ids else ids[0]
        bid = st.selectbox('当前书籍', ids, format_func=names.get, key='book_picker')
        if previous != bid:
            st.session_state.pop('session_picker', None)
            st.session_state.pop('api_pending_question', None)
        st.session_state.api_book = bid
        prefs = st.session_state.api_preferences
        if prefs['last_book_id'] != bid:
            prefs = dict(prefs, last_book_id=bid)
            st.session_state.api_preferences = client.request('PUT', '/api/me/preferences', json=prefs)
        book = client.request('GET', f'/api/books/{segment(bid)}')
        st.caption(f"{book['file_count']} 个文件 · {book['chunk_count']} 个分块 · {book['status']}")
        if book['writable']:
            with st.expander('管理书籍与文件'):
                with st.form('api_rename_book:' + bid):
                    name = st.text_input('修改书名', value=book['name'], max_chars=100, key='api_book_rename:' + bid)
                    if st.form_submit_button('保存书名'):
                        client.request('PATCH', f'/api/books/{segment(bid)}', json={'name': name})
                        st.rerun()
                uploads = st.file_uploader('上传原著（单文件最多 20 MiB）', type=['txt', 'pdf', 'docx'], accept_multiple_files=True, key='upload:' + bid)
                if st.button('上传并建立索引', disabled=not uploads):
                    for file in uploads:
                        raw = file.getvalue()
                        action = f'upload:{bid}:{file.name}:' + hashlib.sha256(raw).hexdigest()
                        with st.spinner('正在解析并建立索引…'):
                            client.request('POST', f'/api/books/{segment(bid)}/files', files={'file': (file.name, raw)}, key=key_for(action))
                        completed(action)
                    st.rerun()
                for file in book['files']:
                    st.caption(file['name'] + ' · ' + file['status'])
                    confirmed = st.checkbox('确认删除文件 ' + file['name'], key='confirm-file:' + file['id'])
                    if st.button('删除文件', key='delete-file:' + file['id'], disabled=not confirmed):
                        client.request('DELETE', f'/api/books/{segment(bid)}/files/{segment(file["id"])}')
                        st.rerun()
                confirmed = st.checkbox('确认删除书籍、文件及全部关联会话', key='confirm-book:' + bid)
                if st.button('删除当前书籍', disabled=not confirmed):
                    client.request('DELETE', f'/api/books/{segment(bid)}')
                    for field in ('api_book', 'api_preferences', 'book_picker', 'session_picker', 'api_pending_question'):
                        st.session_state.pop(field, None)
                    st.rerun()
        else:
            st.caption('此书籍为共享只读资源。')
        return book


def active_book(client, books=None):
    books = books if books is not None else client.all('/api/books')
    if not books:
        return None
    ids = [book['id'] for book in books]
    if 'api_preferences' not in st.session_state:
        st.session_state.api_preferences = client.request('GET', '/api/me/preferences')
    preferences = st.session_state.api_preferences
    selected = st.session_state.get('api_book') or preferences.get('last_book_id')
    if selected not in ids:
        selected = ids[0]
    st.session_state.api_book = selected
    if preferences.get('last_book_id') != selected:
        preferences = dict(preferences, last_book_id=selected)
        st.session_state.api_preferences = client.request('PUT', '/api/me/preferences', json=preferences)
    return client.request('GET', f'/api/books/{segment(selected)}')


def select_library_book(client, books, index):
    book_id = books[index % len(books)]['id']
    if st.session_state.get('api_book') != book_id:
        st.session_state.api_book = book_id
        st.session_state.pop('session_picker', None)
        st.session_state.pop('api_pending_question', None)
    st.rerun()


def manage_book(client, book):
    if not book['writable']:
        st.caption('此书籍为共享只读资源，不能修改书名、文本或删除书籍。')
        return
    with st.expander('管理书籍与文本', expanded=False):
        meta = presentation(book)
        with st.form('library_update_book:' + book['id']):
            name = st.text_input('书名', value=book['name'], max_chars=100, key='library_book_name:' + book['id'])
            author = st.text_input('作者', value=book.get('author') or meta['author'], max_chars=100, key='library_book_author:' + book['id'])
            category = st.text_input('分类', value=book.get('category') or meta['category'], max_chars=50, key='library_book_category:' + book['id'])
            description = st.text_area('书籍简介', value=book.get('description') or meta['description'], max_chars=1000, key='library_book_description:' + book['id'])
            if st.form_submit_button('保存书籍资料', type='primary'):
                client.request('PATCH', f'/api/books/{segment(book["id"])}', json={
                    'name': name, 'author': author, 'category': category, 'description': description,
                })
                st.rerun()
        cover = st.file_uploader('设置封面（PNG、JPEG、WEBP，最大 2 MiB）', type=['png', 'jpg', 'jpeg', 'webp'], key='library_cover:' + book['id'])
        if st.button('保存封面', disabled=not cover, key='library_cover_submit:' + book['id']):
            raw = cover.getvalue()
            client.request('PUT', f'/api/books/{segment(book["id"])}/cover', files={'file': (cover.name, raw, cover.type)})
            st.rerun()
        uploads = st.file_uploader(
            '增加书籍文本（单文件最多 20 MiB）',
            type=['txt', 'pdf', 'docx'],
            accept_multiple_files=True,
            key='library_upload:' + book['id'],
        )
        if st.button('上传并建立索引', disabled=not uploads, key='library_upload_submit:' + book['id']):
            for file in uploads:
                raw = file.getvalue()
                action = f'upload:{book["id"]}:{file.name}:' + hashlib.sha256(raw).hexdigest()
                with st.spinner('正在解析并建立索引…'):
                    client.request('POST', f'/api/books/{segment(book["id"])}/files', files={'file': (file.name, raw)}, key=key_for(action))
                completed(action)
            st.rerun()
        for file in book['files']:
            left, right = st.columns([5, 2], vertical_alignment='center')
            left.caption(file['name'] + ' · ' + file['status'])
            confirmed = right.checkbox('确认删除', key='library_confirm_file:' + file['id'])
            if right.button('删除文本', key='library_delete_file:' + file['id'], disabled=not confirmed):
                client.request('DELETE', f'/api/books/{segment(book["id"])}/files/{segment(file["id"])}')
                st.rerun()
        st.divider()
        confirmed = st.checkbox('确认删除书籍、文本及全部关联会话', key='library_confirm_book:' + book['id'])
        if st.button('删除当前书籍', disabled=not confirmed, key='library_delete_book:' + book['id']):
            client.request('DELETE', f'/api/books/{segment(book["id"])}')
            for field in ('api_book', 'api_preferences', 'book_picker', 'session_picker', 'api_pending_question'):
                st.session_state.pop(field, None)
            st.rerun()


def library_page(client):
    brand()
    st.markdown('<p class="reading-eyebrow">MY LIBRARY</p>', unsafe_allow_html=True)
    st.title('今天想读哪一本？')
    st.markdown('<p class="reading-lead">选择一本书进入阅读空间；书籍、文本和索引维护集中在这里完成。</p>', unsafe_allow_html=True)
    query = st.text_input('搜索书籍', max_chars=100, placeholder='输入书名', label_visibility='collapsed')
    books = client.all('/api/books', q=query)
    categories = ['全部'] + sorted({presentation(book)['category'] for book in books})
    selected_category = st.segmented_control('图书分类', categories, default='全部', key='library_category')
    if selected_category and selected_category != '全部':
        books = [book for book in books if presentation(book)['category'] == selected_category]
    with st.expander('增加书籍', expanded=not books):
        with st.form('library_new_book'):
            name = st.text_input('书籍名称', max_chars=100, key='library_book_name')
            if st.form_submit_button('创建书籍', type='primary'):
                action = 'create-book:' + name
                created = client.request('POST', '/api/books', json={'name': name}, key=key_for(action))
                completed(action)
                st.session_state.api_book = created['id']
                st.rerun()
    if not books:
        st.info('暂无书籍。请先增加书籍，再上传 TXT、PDF 或 DOCX 文本。')
        return
    book = active_book(client, books)
    ids = [item['id'] for item in books]
    index = ids.index(book['id']) if book['id'] in ids else 0
    meta = presentation(book)
    previous_name = books[(index - 1) % len(books)]['name'] if len(books) > 1 else ''
    next_name = books[(index + 1) % len(books)]['name'] if len(books) > 1 else ''
    previous, cover, following = st.columns([1.2, 3, 1.2], vertical_alignment='center')
    if previous.button('← ' + previous_name, use_container_width=True, disabled=len(books) < 2):
        select_library_book(client, books, index - 1)
    with cover:
        if book.get('has_cover'):
            raw, content_type = client.binary(f'/api/books/{segment(book["id"])}/cover')
            source = 'data:' + content_type + ';base64,' + base64.b64encode(raw).decode('ascii')
            cover_content = f'<img class="reading-cover__image" src="{source}" alt="《{html.escape(book["name"])}》封面">'
        else:
            cover_content = (f'<span class="reading-cover__title">{html.escape(book["name"])}</span>'
                             f'<span class="reading-cover__meta">{html.escape(meta["author"])}</span>')
        st.markdown('<div class="reading-shelf"><div class="reading-cover">' + cover_content + '</div></div>', unsafe_allow_html=True)
    if following.button(next_name + ' →', use_container_width=True, disabled=len(books) < 2):
        select_library_book(client, books, index + 1)
    st.markdown(
        '<div class="reading-book-detail">'
        f'<h2>《{html.escape(book["name"])}》</h2>'
        f'<p>{html.escape(meta["author"])} · {html.escape(meta["category"])}</p>'
        f'<p>{html.escape(meta["description"])}</p>'
        f'<span class="reading-status">{book["file_count"]} 个文本 · {book["chunk_count"]} 个分块 · {html.escape(book["status"])}</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    enter, manage = st.columns([2, 1])
    if enter.button('进入阅读空间', type='primary', use_container_width=True):
        st.session_state.app_area = 'reader'
        st.rerun()
    with manage:
        st.caption('封面、作者、简介和分类会随书籍资料保存。')
    manage_book(client, book)


def logout(client):
    try:
        client.request('POST', '/api/auth/logout', json={'refresh_token': client.refresh_token}, refresh=False)
    except APIError as exc:
        show_error(exc)
    else:
        client.access_token = client.refresh_token = ''
        cookie = getattr(getattr(st, 'context', None), 'cookies', {}).get('literary_refresh', '')
        st.session_state.clear()
        st.session_state.api_logged_out_cookie = cookie
        st.rerun()


def settings_page(client, user):
    brand()
    st.markdown('<p class="reading-eyebrow">SETTINGS</p>', unsafe_allow_html=True)
    st.title('设置')
    st.markdown('<p class="reading-lead">账号信息与本次登录的回答模型统一在这里维护。</p>', unsafe_allow_html=True)
    profile, model = st.columns([1, 2], gap='large')
    with profile:
        initial = html.escape((user.get('nickname') or user.get('username') or 'U')[:1].upper())
        st.markdown(
            '<div class="reading-profile">'
            f'<div class="reading-profile__avatar">{initial}</div>'
            f'<h3>{html.escape(user["nickname"])}</h3>'
            f'<p>@{html.escape(user["username"])}</p>'
            f'<p>{html.escape(user["role"])}</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.button('更换头像', disabled=True, use_container_width=True, help='当前阶段仅展示账号映射，暂不保存头像。')
    with model:
        model_settings(client, model)
    st.divider()
    if st.button('退出登录', type='secondary'):
        logout(client)


def home_navigation(area):
    with st.container(key='home_bottom_nav'):
        selected = st.radio(
            '主导航', ['选书', '设置'], horizontal=True,
            index=0 if area == 'library' else 1,
            key='home_navigation', label_visibility='collapsed',
        )
    target = 'library' if selected == '选书' else 'settings'
    if target != area:
        st.session_state.app_area = target
        st.rerun()


def sessions(client, book):
    bid = book['id']
    with st.sidebar:
        rows = client.all(f'/api/books/{segment(bid)}/sessions')
        heading, create = st.columns([5, 1], vertical_alignment='center')
        heading.markdown('<p class="reading-session-heading">阅读会话</p>', unsafe_allow_html=True)
        if create.button('＋', key='reader_new_session', help='新建会话', use_container_width=True):
            action = 'create-session:' + bid
            row = client.request('POST', f'/api/books/{segment(bid)}/sessions', json={}, key=key_for(action))
            completed(action)
            st.session_state.api_selected_session = row['id']
            st.rerun()
        if not rows:
            st.info('请新建会话后提问。')
            return None
        ids = [x['id'] for x in rows]
        pref = st.session_state.api_preferences
        active = st.session_state.get('api_selected_session', pref['active_session_by_book'].get(bid))
        sid = active if active in ids else ids[0]
        st.session_state.api_selected_session = sid
        if pref['active_session_by_book'].get(bid) != sid:
            selections = dict(pref['active_session_by_book'], **{bid: sid})
            st.session_state.api_preferences = client.request('PUT', '/api/me/preferences', json=dict(pref, active_session_by_book=selections))
        event = session_context_menu(
            sessions=[{'id': row['id'], 'name': row['name']} for row in rows],
            active_id=sid,
            key='reader_session_menu:' + bid,
            default=None,
        )
        if event and event.get('event_id') != st.session_state.get('reader_session_event'):
            st.session_state.reader_session_event = event.get('event_id')
            event_sid = event.get('session_id')
            if event_sid in ids and event.get('action') == 'select':
                st.session_state.api_selected_session = event_sid
                st.session_state.pop('api_pending_question', None)
                st.rerun()
            if event_sid in ids and event.get('action') == 'rename':
                client.request('PATCH', f'/api/sessions/{segment(event_sid)}', json={'name': event.get('name', '')})
                st.rerun()
            if event_sid in ids and event.get('action') == 'delete':
                client.request('DELETE', f'/api/sessions/{segment(event_sid)}')
                st.session_state.pop('api_preferences', None)
                st.session_state.pop('api_pending_question', None)
                if st.session_state.get('api_selected_session') == event_sid:
                    st.session_state.pop('api_selected_session', None)
                st.rerun()
        return sid


def chat(client, book, sid):
    if not sid:
        return
    session_rows = client.all(f'/api/books/{segment(book["id"])}/sessions')
    session_name = next((row['name'] for row in session_rows if row['id'] == sid), '阅读对话')
    st.markdown(
        '<div class="reading-chat-heading"><p class="reading-eyebrow">阅读对话</p>'
        f'<h1>{html.escape(session_name)}</h1>'
        f'<p>回答将检索《{html.escape(book["name"])}》的已上传文本，并给出原文依据。</p></div>',
        unsafe_allow_html=True,
    )
    pending = st.session_state.get('api_pending_question')
    if pending and pending['sid'] != sid:
        pending = None
        st.session_state.pop('api_pending_question', None)
    question = st.chat_input('请输入你的问题…', disabled=bool(pending))
    retry = False
    if pending:
        st.warning('上次请求未确认成功：' + pending['question'])
        retry = st.button('使用原请求重试')
        if st.button('结束此请求，允许重新提问'):
            st.session_state.pop('api_pending_question', None)
            st.rerun()
    if question:
        pending = {'sid': sid, 'question': question, 'key': str(uuid.uuid4())}
        st.session_state.api_pending_question = pending
    if question or retry:
        try:
            with st.spinner('正在分析问题并生成回答…'):
                client.request('POST', f'/api/sessions/{segment(sid)}/questions', json={'question': pending['question']}, key=pending['key'])
            st.session_state.pop('api_pending_question', None)
            st.rerun()
        except APIError as exc:
            show_error(exc)
            st.info('重试会保留原幂等键。若后端明确报告原结果未知，请先检查历史，再决定是否重新提问。')
    for turn in client.all(f'/api/sessions/{segment(sid)}/messages'):
        with st.chat_message('user'):
            st.write(turn['question'])
        with st.chat_message('assistant'):
            if turn['rejected']:
                st.warning(turn['answer'])
            else:
                if turn['soft_reject']:
                    st.info('相关度较低：回答依据有限原文。')
                st.write(turn['answer'])
            for call in turn.get('tool_calls', []):
                if call.get('name') == 'show_relationship_graph':
                    st.caption('🔧 已调用工具：人物关系图')
                    render_mermaid(call['result']['code'])
                    with st.expander('查看 Mermaid 源码', expanded=False):
                        st.code(call['result']['code'], language='mermaid')
                elif call.get('name') == 'lookup_characters':
                    st.caption('🔧 已调用工具：人物信息查询')
                    items = call['result']['items']
                    if items:
                        for row in items:
                            with st.expander(f"{row['name']} · {row.get('identity', '')}", expanded=len(items) == 1):
                                st.write(row.get('description', ''))
                                st.caption('家族：' + (row.get('family') or '未知'))
                                for relation in call['result'].get('relations', {}).get(row['id'], []):
                                    st.write(f"{relation.get('target_name', '未知')}：{relation.get('relation', '')}")
                    else:
                        st.info('人物表中没有符合条件的记录。')
                    with st.expander('查看原始 JSON', expanded=False):
                        st.json(items)
                elif call.get('name') == 'lookup_events':
                    st.caption('🔧 已调用工具：事件查询')
                    items = call['result']['items']
                    if items:
                        for row in items:
                            with st.expander(f"{row.get('name', '')} · {row.get('chapter', '')}", expanded=len(items) == 1):
                                st.write(row.get('description', ''))
                    else:
                        st.info('事件表中没有符合条件的记录。')
                    with st.expander('查看原始 JSON', expanded=False):
                        st.json(items)
            if turn['min_distance'] is not None:
                st.caption(f"检索距离：{turn['min_distance']:.3f}（越小越相关，并非回答正确率）")
            if turn['sources']:
                with st.expander('原文依据'):
                    for source in turn['sources']:
                        meta = source['metadata']
                        st.caption(f"{meta.get('file_name') or '未知文件'} · {meta.get('chapter') or '未知章节'}")
                        st.write(source['text'])


def render_mermaid(code):
    escaped = html.escape(code)
    st.components.v1.html('<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script><pre class="mermaid">' + escaped + '</pre><script>mermaid.initialize({startOnLoad:true,securityLevel:"strict"});</script>', height=650, scrolling=True)


def characters(client, book):
    st.header('人物关系 · ' + book['name'])
    if not book['capabilities']['characters']:
        st.info('此书籍尚未配置人物关系数据；上传原著不会自动生成关系图。')
        return
    prefix = f'/api/books/{segment(book["id"])}'
    mode = st.radio('功能选择', ['人物列表', '关系图', '事件表'], horizontal=True)
    if mode == '人物列表':
        families = client.request('GET', prefix + '/families')['items']
        family = st.selectbox('按家族筛选', ['全部'] + families)
        items = client.all(prefix + '/characters', **({'family': family} if family != '全部' else {}))
        columns = st.columns(3)
        for index, char in enumerate(items):
            with columns[index % 3], st.expander(char['name'] + ' · ' + char.get('identity', '')):
                st.write(char.get('description', ''))
                st.caption('家族：' + char.get('family', '未知'))
                relations = client.request('GET', prefix + '/characters/' + segment(char['id']) + '/relations')['items']
                for row in relations:
                    st.write(row['target_name'] + '：' + row['relation'])
    elif mode == '关系图':
        scope = st.selectbox('关系图类型', ['all', 'character', 'family'], format_func=lambda x: {'all': '全部人物', 'character': '人物关系网', 'family': '家族关系'}[x])
        params = {'scope': scope}
        if scope == 'character':
            items = client.all(prefix + '/characters')
            if not items:
                st.info('暂无人物')
                return
            names = {x['id']: x['name'] for x in items}
            params['character_id'] = st.selectbox('中心人物', list(names), format_func=names.get)
        graph = client.request('GET', prefix + '/relationship-graph', params=params)
        with st.expander('查看 Mermaid 源码'):
            st.code(graph['code'], language='mermaid')
        render_mermaid(graph['code'])
    else:
        for row in client.all(prefix + '/events'):
            with st.expander(row.get('name', '') + ' · ' + row.get('chapter', '')):
                st.write(row.get('description', ''))


def exercise_result(record):
    st.success(f"正确 {record['correct']} / {record['total']} · 正确率 {record['accuracy']}%")
    for row in record['questions']:
        with st.expander(('✅ ' if row['correct'] else '❌ ') + row['question']):
            st.write('你的答案：' + row['options'][row['selected']])
            st.write('正确答案：' + row['options'][row['answer']])
            st.write('解析：' + row.get('explanation', ''))
            st.write('原著出处：' + row['source'])


def exercise_charts(stats):
    import json
    import streamlit.components.v1 as components
    chapters = stats['chapters']
    options = [
        {'title': {'text': '章节正确率'}, 'tooltip': {'trigger': 'axis'}, 'xAxis': {'type': 'category', 'data': [r['chapter'] for r in chapters], 'axisLabel': {'rotate': 30}}, 'yAxis': {'type': 'value', 'min': 0, 'max': 100, 'axisLabel': {'formatter': '{value}%'}}, 'series': [{'type': 'bar', 'data': [r['accuracy'] for r in chapters]}]},
        {'title': {'text': '历次自测正确率'}, 'tooltip': {'trigger': 'axis'}, 'xAxis': {'type': 'category', 'data': [str(i + 1) for i in range(len(stats['trend']))]}, 'yAxis': {'type': 'value', 'min': 0, 'max': 100}, 'series': [{'type': 'line', 'data': [r['accuracy'] for r in stats['trend']]}]}
    ]
    encoded = json.dumps(options, ensure_ascii=True).replace('<', r'\u003c')
    components.html('<div id="error"></div><div id="chapters" style="height:320px"></div><div id="trend" style="height:280px"></div>'
        + '<script src="https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js" onerror="document.getElementById(\'error\').textContent=\'图表资源加载失败，请查看下方统计表\'"></script>'
        + '<script>if(window.echarts){const options=' + encoded + ';const charts=["chapters","trend"].map((id,i)=>{const c=echarts.init(document.getElementById(id));c.setOption(options[i]);return c;});window.addEventListener("resize",()=>charts.forEach(c=>c.resize()));}</script>', height=630)


def exercises(client, book):
    st.header('习题自测 · ' + book['name'])
    prefix = f'/api/books/{segment(book["id"])}'
    state_key = 'self_test:' + book['id']
    practice, history = st.tabs(['基础习题自测', '历史记录与分析'])
    with practice:
        if not book['capabilities']['exercises']:
            st.info('习题数据未就绪')
        else:
            chapters = client.request('GET', prefix + '/exercise-chapters')['items']
            selected = st.multiselect('选择章节（可多选）', chapters, key=state_key + ':chapters')
            difficulty = st.selectbox('难度', [None, 'easy', 'medium', 'hard'], format_func=lambda x: {None: '全部', 'easy': '简单', 'medium': '中等', 'hard': '困难'}[x], key=state_key + ':difficulty')
            if st.button('开始自测', key=state_key + ':start'):
                if not selected:
                    st.warning('请先选择章节')
                else:
                    payload = {'chapters': selected, 'difficulty': difficulty}
                    action = state_key + ':start:' + repr(payload)
                    st.session_state[state_key] = client.request('POST', prefix + '/exercise-attempts', json=payload, key=key_for(action))
                    completed(action)
                    st.rerun()
            attempt = st.session_state.get(state_key)
            if attempt:
                if attempt.get('result'):
                    exercise_result(attempt['result'])
                else:
                    st.caption(f"共 {len(attempt['questions'])} 道题，请全部作答后提交")
                    answer_area = st.empty()
                    with answer_area.container(), st.form('answers:' + attempt['id']):
                        answers = {}
                        for i, row in enumerate(attempt['questions'], 1):
                            st.markdown(f"**{i}. {row['question']}** · {row['chapter']}")
                            answers[row['id']] = st.radio('选择答案', range(len(row['options'])), format_func=lambda n, opts=row['options']: opts[n], index=None, key=attempt['id'] + ':' + row['id'])
                        submit = st.form_submit_button('提交全部答案')
                    if submit:
                        if any(value is None for value in answers.values()):
                            st.warning('请先选择答案')
                        else:
                            attempt['result'] = client.request('POST', prefix + '/exercise-attempts/' + attempt['id'] + '/submit', json={'answers': answers})
                            answer_area.empty()
                            st.rerun()
    with history:
        stats = client.request('GET', prefix + '/exercise-statistics')
        if not stats['attempts']:
            st.info('暂无自测记录，完成一次提交后即可查看分析。')
        else:
            st.metric('累计正确率', f"{stats['accuracy']}%", help='所有已提交题目的正确次数 / 作答总次数；重复练习计入统计')
            st.caption(f"自测 {stats['attempts']} 次 · 作答 {stats['total']} 题 · 答对 {stats['correct']} 题")
            exercise_charts(stats)
            st.dataframe([{'章节': r['chapter'], '作答次数': r['total'], '正确次数': r['correct'], '正确率（%）': r['accuracy']} for r in stats['chapters']], hide_index=True, use_container_width=True)
            page = st.number_input('历史页码', min_value=1, value=1, step=1, key=state_key + ':history_page')
            records = client.request('GET', prefix + '/exercise-attempts', params={'page': page, 'page_size': 10})
            for record in records['items']:
                with st.expander(record['submitted_at'][:19].replace('T', ' ') + ' UTC · ' + str(record['accuracy']) + '%'):
                    exercise_result(record)


def run():
    st.set_page_config(page_title='伴读精灵', layout='wide')
    client, user = require_client()
    apply_theme()
    try:
        if 'app_area' not in st.session_state:
            st.session_state.app_area = 'reader' if st.session_state.get('api_book') else 'library'
        area = st.session_state.app_area
        if area == 'library':
            library_page(client)
            home_navigation(area)
        elif area == 'settings':
            settings_page(client, user)
            home_navigation(area)
        else:
            book = active_book(client)
            if not book:
                st.session_state.app_area = 'library'
                st.rerun()
            with st.sidebar:
                back, logo = st.columns([1, 5], gap='small', vertical_alignment='center')
                if back.button('←', key='reader_back_to_library', help='返回书架', use_container_width=True):
                    st.session_state.app_area = 'library'
                    st.rerun()
                logo.markdown('<div class="reading-reader-brand"><span class="reading-brand__mark">书</span><strong>伴读精灵</strong></div>', unsafe_allow_html=True)
                st.markdown(
                    '<div class="reading-current-book"><span class="reading-book-spine">'
                    f'{html.escape(book["name"][:6])}</span><div><small>当前阅读</small>'
                    f'<h3>《{html.escape(book["name"])}》</h3>'
                    f'<small>{html.escape(presentation(book)["author"])}</small></div></div>',
                    unsafe_allow_html=True,
                )
            sid = sessions(client, book)
            page_aliases = {'智能问答': '问问题', '人物关系': '关系图谱', '习题自测': '做题', '练习题': '做题'}
            if st.session_state.get('api_page') in page_aliases:
                st.session_state.api_page = page_aliases[st.session_state.api_page]
            saved = client.request('GET', '/api/auth/model-settings')
            source = '本次登录配置' if saved['source'] == 'login' else '项目默认配置'
            mode = '本地模型' if saved['mode'] == 'ollama' else '登录 API'
            with st.container(key='reader_navigation'):
                navigation, engine = st.columns([3, 2], vertical_alignment='center')
                with navigation:
                    page = st.radio('选择页面', ['问问题', '关系图谱', '做题'], horizontal=True, key='api_page', label_visibility='collapsed')
                with engine:
                    st.radio('回答模型选择', ['本地模型', '登录 API'], horizontal=True, index=0 if mode == '本地模型' else 1, disabled=True, key='reader_engine', label_visibility='collapsed')
                st.markdown('<div class="reading-reader-divider"></div>', unsafe_allow_html=True)
            st.caption(f'当前回答来源：{mode} · {saved["model"]} · {source}。模型配置在“设置”中维护。')
            if page == '问问题':
                chat(client, book, sid)
            elif page == '关系图谱':
                characters(client, book)
            else:
                exercises(client, book)
    except APIError as exc:
        show_error(exc)
    finally:
        st.session_state.api_access, st.session_state.api_refresh = client.access_token, client.refresh_token
