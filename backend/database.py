"""SQLite transactions, durable idempotency and read/write resource leases."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .contracts import Error, missing


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


SCHEMA = '''
CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,name TEXT NOT NULL,
 author TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '未分类',description TEXT NOT NULL DEFAULT '',
 cover BLOB,cover_mime TEXT,created_at TEXT,visibility TEXT NOT NULL DEFAULT 'private',dataset TEXT,status TEXT NOT NULL DEFAULT 'ready');
CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
 name TEXT NOT NULL,size_bytes INTEGER,chunk_count INTEGER NOT NULL DEFAULT 0,content_hash TEXT,status TEXT NOT NULL,uploaded_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS file_content ON files(book_id,content_hash) WHERE content_hash IS NOT NULL;
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
 name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preferences(owner_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency(owner_id INTEGER NOT NULL,scope TEXT NOT NULL,key TEXT NOT NULL,fingerprint TEXT NOT NULL,
 state TEXT NOT NULL,result TEXT,status INTEGER,created REAL NOT NULL,PRIMARY KEY(owner_id,scope,key));
CREATE TABLE IF NOT EXISTS leases(resource TEXT NOT NULL,holder TEXT NOT NULL,mode TEXT NOT NULL,PRIMARY KEY(resource,holder));
CREATE TABLE IF NOT EXISTS tombstones(owner_id INTEGER NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,PRIMARY KEY(owner_id,kind,id));
CREATE TABLE IF NOT EXISTS exercise_attempts(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,created_at TEXT NOT NULL,questions TEXT NOT NULL,result TEXT);
CREATE INDEX IF NOT EXISTS exercise_owner ON exercise_attempts(owner_id,book_id);
CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY,created TEXT NOT NULL,details TEXT NOT NULL);
'''


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript(SCHEMA)
            columns = {row['name'] for row in db.execute('PRAGMA table_info(books)')}
            additions = {
                'author': "TEXT NOT NULL DEFAULT ''",
                'category': "TEXT NOT NULL DEFAULT '未分类'",
                'description': "TEXT NOT NULL DEFAULT ''",
                'cover': 'BLOB',
                'cover_mime': 'TEXT',
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE books ADD COLUMN {name} {definition}')

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def book(db, user, book_id, write=False):
        row = db.execute('SELECT * FROM books WHERE id=? AND (owner_id=? OR visibility=?)', (book_id, user['id'], 'shared')).fetchone()
        if not row:
            missing()
        if write and (row['owner_id'] != user['id'] or row['visibility'] == 'shared' and user['role'] != 'admin'):
            raise Error(403, 'FORBIDDEN', '此书籍只读')
        return dict(row)

    @classmethod
    def session(cls, db, user, session_id):
        row = db.execute('SELECT * FROM sessions WHERE id=? AND owner_id=?', (session_id, user['id'])).fetchone()
        if not row:
            missing()
        cls.book(db, user, row['book_id'])
        return dict(row)

    @staticmethod
    def acquire(db, resources):
        holder = str(uuid.uuid4())
        for resource, mode in resources:
            rows = db.execute('SELECT mode FROM leases WHERE resource=?', (resource,)).fetchall()
            if rows and (mode == 'write' or any(row['mode'] == 'write' for row in rows)):
                raise Error(409, 'SESSION_BUSY', '资源正在处理中，请稍后重试')
            db.execute('INSERT INTO leases VALUES (?,?,?)', (resource, holder, mode))
        return holder

    def release(self, holder):
        with self.tx() as db:
            db.execute('DELETE FROM leases WHERE holder=?', (holder,))

    @staticmethod
    def reserve(db, user, scope, key, payload):
        if not key or not 1 <= len(key) <= 128:
            raise Error(422, 'VALIDATION_ERROR', '必须提供 1～128 字符的 Idempotency-Key')
        fingerprint = hashlib.sha256(dump(payload).encode()).hexdigest()
        row = db.execute('SELECT * FROM idempotency WHERE owner_id=? AND scope=? AND key=?', (user['id'], scope, key)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint:
                raise Error(409, 'IDEMPOTENCY_CONFLICT', '同一幂等键不能用于不同参数')
            if row['state'] == 'pending':
                raise Error(409, 'SESSION_BUSY', '原请求仍在处理，请保留原幂等键重试')
            if row['state'] == 'unknown':
                raise Error(409, 'RESULT_UNKNOWN', '原请求结果未知；确认后请明确发起新请求')
            return dict(row)
        db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?,?,?,?)', (user['id'], scope, key, fingerprint, 'pending', None, None, time.time()))
        return None

    @staticmethod
    def finish(db, user, scope, key, result, status=201, state='done'):
        db.execute('UPDATE idempotency SET state=?,result=?,status=? WHERE owner_id=? AND scope=? AND key=?', (state, dump(result), status, user['id'], scope, key))

    @staticmethod
    def replay(row):
        result = json.loads(row['result'])
        if row['state'] == 'failed':
            raise Error(row['status'], result['code'], result['message'])
        return result, row['status'], True

    @staticmethod
    def deleted(db, user, kind, resource_id):
        return db.execute('SELECT 1 FROM tombstones WHERE owner_id=? AND kind=? AND id=?', (user['id'], kind, resource_id)).fetchone() is not None

    @staticmethod
    def tombstone(db, user, kind, resource_id):
        db.execute('INSERT OR IGNORE INTO tombstones VALUES (?,?,?)', (user['id'], kind, resource_id))

    @staticmethod
    def prune_preferences(db):
        for row in db.execute('SELECT * FROM preferences').fetchall():
            pref = json.loads(row['payload'])
            uid = row['owner_id']
            valid = {r['id'] for r in db.execute('SELECT id FROM books WHERE owner_id=? OR visibility=?', (uid, 'shared'))}
            if pref.get('last_book_id') not in valid:
                pref['last_book_id'] = None
            pref['active_session_by_book'] = {bid: sid for bid, sid in pref.get('active_session_by_book', {}).items() if bid in valid and db.execute('SELECT 1 FROM sessions WHERE id=? AND book_id=? AND owner_id=?', (sid, bid, uid)).fetchone()}
            db.execute('UPDATE preferences SET payload=? WHERE owner_id=?', (dump(pref), uid))

    def recover_questions(self):
        # Called only while holding the exclusive backend process lock.
        with self.tx() as db:
            for row in db.execute("SELECT * FROM idempotency WHERE state='generated'").fetchall():
                result = json.loads(row['result'])
                sid = row['scope'].removeprefix('question:')
                if db.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                    self.save_turn(db, sid, result)
                    db.execute("UPDATE idempotency SET state='done',result=?,status=201 WHERE owner_id=? AND scope=? AND key=?", (dump(result), row['owner_id'], row['scope'], row['key']))
            db.execute("UPDATE idempotency SET state='unknown' WHERE state='pending' AND scope LIKE 'question:%'")
            db.execute('DELETE FROM leases')

    @staticmethod
    def save_turn(db, sid, result):
        first_turn = not db.execute('SELECT 1 FROM turns WHERE session_id=? LIMIT 1', (sid,)).fetchone()
        if first_turn:
            title = ' '.join(result['question'].split())[:100] or '新会话'
            db.execute("UPDATE sessions SET name=? WHERE id=? AND name='新会话'", (title, sid))
        cursor = db.execute('INSERT INTO turns(session_id,payload) VALUES (?,?)', (sid, dump(result)))
        result['turn_id'] = cursor.lastrowid
        db.execute('UPDATE turns SET payload=? WHERE id=?', (dump(result), cursor.lastrowid))
        db.execute('UPDATE sessions SET updated_at=? WHERE id=?', (now(), sid))
