"""User-scoped conversations; history and inference stay on the server."""
import json
import sqlite3
import uuid
from .contracts import Error, paginate
from .database import dump, now
from .agent_tools import (AGENT_TOOLS, fallback_arguments, fallback_event_arguments,
                          requested_tool_name, run_character_lookup_tool,
                          run_event_lookup_tool, run_relationship_graph_tool)


class Conversations:
    def __init__(self, database, adapter, auth, business=None):
        self.database, self.adapter, self.auth, self.business = database, adapter, auth, business

    @staticmethod
    def describe(row):
        return {k: row[k] for k in ('id', 'book_id', 'name', 'created_at', 'updated_at')}

    def list(self, user, book_id, page, page_size):
        with self.database.tx() as db:
            self.database.book(db, user, book_id)
            items = [self.describe(r) for r in db.execute('SELECT * FROM sessions WHERE book_id=? AND owner_id=? ORDER BY updated_at DESC,id', (book_id, user['id']))]
            for item in items:
                if item['name'] == '新会话':
                    first = db.execute('SELECT payload FROM turns WHERE session_id=? ORDER BY id LIMIT 1', (item['id'],)).fetchone()
                    if first:
                        item['name'] = ' '.join(json.loads(first[0])['question'].split())[:100] or '新会话'
        return paginate(items, page, page_size)

    def create(self, user, book_id, name, key):
        scope = f'sessions:{book_id}'
        with self.database.tx() as db:
            book = self.database.book(db, user, book_id)
            replay = self.database.reserve(db, user, scope, key, {'name': name})
            if replay:
                return self.database.replay(replay)
            if book['status'] == 'deleting':
                raise Error(409, 'BOOK_NOT_READY', '书籍正在删除')
            sid, timestamp = str(uuid.uuid4()), now()
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)', (sid, user['id'], book_id, name, timestamp, timestamp))
            result = self.describe(self.database.session(db, user, sid))
            self.database.finish(db, user, scope, key, result)
        return result, 201, False

    def rename(self, user, sid, name):
        with self.database.tx() as db:
            self.database.session(db, user, sid)
            if db.execute("SELECT 1 FROM idempotency WHERE scope=? AND state='generated'", (f'question:{sid}',)).fetchone():
                raise Error(409, 'SESSION_BUSY', '会话有生成结果待保存，请先使用原请求重试')
            holder = self.database.acquire(db, [(f'session:{sid}', 'write')])
            db.execute('UPDATE sessions SET name=?,updated_at=? WHERE id=?', (name, now(), sid))
            result = self.describe(self.database.session(db, user, sid))
            db.execute('DELETE FROM leases WHERE holder=?', (holder,))
        return result

    def history(self, user, sid, page, page_size):
        with self.database.tx() as db:
            self.database.session(db, user, sid)
            rows = db.execute('SELECT id,payload FROM turns WHERE session_id=? ORDER BY id', (sid,)).fetchall()
            items = [dict(json.loads(r['payload']), turn_id=r['id']) for r in rows]
        return paginate(items, page, page_size)

    def delete(self, user, sid, clear=False):
        with self.database.tx() as db:
            if not clear and self.database.deleted(db, user, 'session', sid):
                return {'deleted': True}
            self.database.session(db, user, sid)
            if db.execute("SELECT 1 FROM idempotency WHERE scope=? AND state='generated'", (f'question:{sid}',)).fetchone():
                raise Error(409, 'SESSION_BUSY', '会话有回答待保存，请先重试原问答请求')
            holder = self.database.acquire(db, [(f'session:{sid}', 'write')])
            # Erase answer bodies as well as visible history, retain only a receipt/hash.
            db.execute("UPDATE idempotency SET state='failed',result=?,status=410 WHERE owner_id=? AND scope=?", (dump({'code': 'RESOURCE_REMOVED', 'message': '原问答历史已清除，不再重放内容'}), user['id'], f'question:{sid}'))
            if clear:
                db.execute('DELETE FROM turns WHERE session_id=?', (sid,))
                db.execute("UPDATE sessions SET name='新会话',updated_at=? WHERE id=?", (now(), sid))
            else:
                db.execute('DELETE FROM sessions WHERE id=?', (sid,))
                self.database.tombstone(db, user, 'session', sid)
                self.database.prune_preferences(db)
            db.execute('DELETE FROM leases WHERE holder=?', (holder,))
        return {'cleared': True} if clear else {'deleted': True}

    def preferences(self, user, value=None):
        with self.database.tx() as db:
            if value is not None:
                if value.last_book_id:
                    self.database.book(db, user, value.last_book_id)
                for bid, sid in value.active_session_by_book.items():
                    session = self.database.session(db, user, sid)
                    if session['book_id'] != bid:
                        raise Error(422, 'VALIDATION_ERROR', '偏好中的会话不属于指定书籍')
                payload = dump(value.model_dump())
                db.execute('INSERT INTO preferences VALUES (?,?) ON CONFLICT(owner_id) DO UPDATE SET payload=excluded.payload', (user['id'], payload))
            self.database.prune_preferences(db)
            row = db.execute('SELECT payload FROM preferences WHERE owner_id=?', (user['id'],)).fetchone()
            return json.loads(row[0]) if row else {'last_book_id': None, 'active_session_by_book': {}}

    @staticmethod
    def normalize(question, answer):
        if not isinstance(answer.get('answer'), str) or not answer['answer'].strip():
            raise Error(502, 'MODEL_UPSTREAM_ERROR', '模型返回为空或格式无效')
        sources = []
        for source in answer.get('sources', []):
            meta = source.get('metadata') or {}
            # Explicit allow-list: never return upstream paths or arbitrary metadata.
            sources.append({'text': str(source.get('text', '')), 'metadata': {k: meta.get(k) for k in ('file_id', 'file_name', 'chapter')}, 'distance': source.get('distance')})
        tool_calls = []
        for call in answer.get('tool_calls', []):
            result = call.get('result') or {}
            name, output = call.get('name'), None
            if name == 'show_relationship_graph' and result.get('format') == 'mermaid' and isinstance(result.get('code'), str):
                output = {'format': 'mermaid', 'code': result['code']}
            elif name == 'lookup_characters' and result.get('format') == 'characters' and isinstance(result.get('items'), list):
                fields = ('id', 'name', 'identity', 'description', 'family', 'role')
                relation_fields = ('source_id', 'target_id', 'target_name', 'relation', 'type')
                relations = result.get('relations') if isinstance(result.get('relations'), dict) else {}
                safe_relations = {
                    str(character_id): [{key: row.get(key) for key in relation_fields} for row in rows if isinstance(row, dict)]
                    for character_id, rows in relations.items() if isinstance(rows, list)
                }
                output = {'format': 'characters', 'items': [{key: row.get(key, '') for key in fields} for row in result['items'] if isinstance(row, dict)], 'relations': safe_relations}
            elif name == 'lookup_events' and result.get('format') == 'events' and isinstance(result.get('items'), list):
                fields = ('id', 'name', 'chapter', 'description', 'characters')
                output = {'format': 'events', 'items': [{key: row.get(key, [] if key == 'characters' else '') for key in fields} for row in result['items'] if isinstance(row, dict)]}
            if output is None:
                raise Error(502, 'TOOL_RESULT_ERROR', '工具返回格式无效')
            tool_calls.append({'name': name, 'arguments': call.get('arguments') or {}, 'result': output})
        return {'question': question, 'answer': answer['answer'], 'sources': sources, 'tool_calls': tool_calls, 'rejected': bool(answer.get('rejected')), 'soft_reject': bool(answer.get('soft_reject')), 'min_distance': answer.get('min_distance'), 'created_at': now()}

    def tool_answer(self, user, bid, question, settings):
        expected_name = requested_tool_name(question)
        if self.business is None or expected_name is None:
            return None
        characters = self.business.characters(user, bid, None, 1, 100)['items']
        available = [tool for tool in AGENT_TOOLS if tool['function']['name'] == expected_name]
        decision = self.adapter.choose_tool(question, settings, available) if hasattr(self.adapter, 'choose_tool') else None
        if not decision or decision.get('name') != expected_name:
            arguments = fallback_event_arguments(question, characters) if expected_name == 'lookup_events' else fallback_arguments(question, characters)
            decision = {'name': expected_name, 'arguments': arguments}
        fallback = fallback_event_arguments(question, characters) if expected_name == 'lookup_events' else fallback_arguments(question, characters)
        raw_model_arguments = decision.get('arguments') if isinstance(decision.get('arguments'), dict) else {}
        model_arguments = {key: value for key, value in raw_model_arguments.items() if value not in (None, '')}
        arguments = dict(fallback, **model_arguments)
        requested_name = arguments.get('character_name')
        if requested_name and requested_name not in {row.get('name') for row in characters}:
            arguments = fallback_event_arguments(question, characters) if expected_name == 'lookup_events' else fallback_arguments(question, characters)
        runners = {
            'show_relationship_graph': run_relationship_graph_tool,
            'lookup_characters': run_character_lookup_tool,
            'lookup_events': run_event_lookup_tool,
        }
        call = runners[expected_name](self.business, user, bid, arguments)
        count = len(call['result'].get('items', []))
        messages = {
            'show_relationship_graph': '已调用人物关系图工具，结果如下。',
            'lookup_characters': f'已调用人物信息查询工具，找到 {count} 条人物记录。',
            'lookup_events': f'已调用事件查询工具，找到 {count} 条事件记录。',
        }
        return {'answer': messages[expected_name], 'sources': [], 'tool_calls': [call], 'rejected': False, 'soft_reject': False}

    # Kept for callers/tests written against the first tool-only implementation.
    def relationship_answer(self, user, bid, question, settings):
        return self.tool_answer(user, bid, question, settings)

    def ask(self, user, login_sid, sid, question, key):
        scope = f'question:{sid}'
        with self.database.tx() as db:
            session = self.database.session(db, user, sid)
            replay = self.database.reserve(db, user, scope, key, {'question': question})
            if replay:
                if replay['state'] == 'generated':
                    holder = self.database.acquire(db, [(f'book:{session["book_id"]}', 'read'), (f'session:{sid}', 'write')])
                    result = json.loads(replay['result'])
                    self.database.save_turn(db, sid, result)
                    self.database.finish(db, user, scope, key, result)
                    db.execute('DELETE FROM leases WHERE holder=?', (holder,))
                    return result, 201, True
                return self.database.replay(replay)
            bid = session['book_id']
            book = self.database.book(db, user, bid)
            if book['status'] != 'ready' or not db.execute("SELECT 1 FROM files WHERE book_id=? AND status='ready'", (bid,)).fetchone():
                raise Error(409, 'BOOK_NOT_READY', '请先上传文件并完成索引')
            holder = self.database.acquire(db, [(f'book:{bid}', 'read'), (f'session:{sid}', 'write')])
            history = [json.loads(r[0]) for r in db.execute('SELECT payload FROM turns WHERE session_id=? ORDER BY id', (sid,))]
        try:
            settings = self.auth.settings(login_sid)
            answer = self.tool_answer(user, bid, question, settings)
            if answer is None:
                answer = self.adapter.answer(bid, question, history, settings)
            if answer.get('error'):
                if answer['error'] in ('Timeout', 'ReadTimeout', 'ConnectTimeout'):
                    raise Error(504, 'UPSTREAM_TIMEOUT', '模型请求超时')
                raise Error(502, 'MODEL_UPSTREAM_ERROR', answer.get('error_message') or '模型请求失败')
            result = self.normalize(question, answer)
            # Separate durable checkpoint allows retrying only the database save.
            with self.database.tx() as db:
                self.database.finish(db, user, scope, key, result, 201, 'generated')
            try:
                with self.database.tx() as db:
                    self.database.save_turn(db, sid, result)
                    self.database.finish(db, user, scope, key, result)
            except sqlite3.Error:
                raise Error(503, 'SAVE_PENDING', '回答已生成但保存待重试，请使用原幂等键') from None
            return result, 201, False
        except Error as exc:
            if exc.code != 'SAVE_PENDING':
                with self.database.tx() as db:
                    self.database.finish(db, user, scope, key, {'code': exc.code, 'message': exc.message}, exc.status, 'failed')
            raise
        except Exception as exc:
            status, code = (504, 'UPSTREAM_TIMEOUT') if type(exc).__name__ in ('Timeout', 'ReadTimeout', 'ConnectTimeout') else (503, 'DEPENDENCY_UNAVAILABLE')
            with self.database.tx() as db:
                # If storing the generated checkpoint itself failed, never retry the provider.
                db.execute("UPDATE idempotency SET state='unknown' WHERE owner_id=? AND scope=? AND key=? AND state='pending'", (user['id'], scope, key))
            raise Error(status, code, '问答执行失败，请检查后端依赖；不要自动重发新请求') from None
        finally:
            self.database.release(holder)
