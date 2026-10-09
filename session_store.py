"""Transactional SQLite storage for book-scoped conversations (no model dependencies)."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "sessions.sqlite3"


class SessionStore:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, book_id TEXT NOT NULL, name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                CREATE INDEX IF NOT EXISTS sessions_book ON sessions(book_id);
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id, id);
                CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise ValueError("会话名称应为 1–100 个字符")
        return name.strip()

    @staticmethod
    def _require(db, session_id, book_id):
        row = db.execute("SELECT * FROM sessions WHERE id=? AND book_id=?", (session_id, book_id)).fetchone()
        if row is None:
            raise ValueError("会话不存在或不属于当前书籍")
        return dict(row)

    @staticmethod
    def _pref(db, key, value):
        db.execute("INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def create(self, book_id, name="新会话"):
        if not isinstance(book_id, str) or not book_id:
            raise ValueError("请选择书籍")
        name = self._name(name)
        session_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id,book_id,name) VALUES (?,?,?)", (session_id, book_id, name))
            self._select(db, session_id, book_id)
        return session_id

    def list(self, book_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sessions WHERE book_id=? ORDER BY updated_at DESC, rowid DESC", (book_id,))]

    def _select(self, db, session_id, book_id):
        self._require(db, session_id, book_id)
        self._pref(db, "active:" + book_id, session_id)
        self._pref(db, "last_book", book_id)

    def select(self, session_id, book_id):
        with self.connect() as db:
            self._select(db, session_id, book_id)

    def preference(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def active(self, book_id):
        sessions = self.list(book_id)
        selected = self.preference("active:" + book_id)
        return next((s["id"] for s in sessions if s["id"] == selected), sessions[0]["id"] if sessions else None)

    def rename(self, session_id, book_id, name):
        name = self._name(name)
        with self.connect() as db:
            self._require(db, session_id, book_id)
            db.execute("UPDATE sessions SET name=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (name, session_id))

    def delete(self, session_id, book_id):
        with self.connect() as db:
            self._require(db, session_id, book_id)
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            db.execute("DELETE FROM preferences WHERE key=? AND value=?", ("active:" + book_id, session_id))

    def history(self, session_id, book_id):
        with self.connect() as db:
            self._require(db, session_id, book_id)
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM turns WHERE session_id=? ORDER BY id", (session_id,))]

    def append(self, session_id, book_id, turn):
        if turn.get("error") or not isinstance(turn.get("question"), str) or not isinstance(turn.get("answer"), str):
            raise ValueError("仅保存完整且成功的问答")
        payload = json.dumps(turn, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            self._require(db, session_id, book_id)
            db.execute("INSERT INTO turns(session_id,payload) VALUES (?,?)", (session_id, payload))
            db.execute("UPDATE sessions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (session_id,))

    def clear(self, session_id, book_id):
        with self.connect() as db:
            self._require(db, session_id, book_id)
            db.execute("DELETE FROM turns WHERE session_id=?", (session_id,))

    def delete_book(self, book_id, history_path=None, book_name=None):
        """Remove all book conversations and corresponding legacy history."""
        with self.connect() as db:
            titles = {row[0][len("migrated:"):] for row in db.execute(
                "SELECT key FROM preferences WHERE key LIKE 'migrated:%' AND value=?", (book_id,)
            )}
            if book_name:
                titles.add(book_name)
            if history_path and Path(history_path).exists():
                path = Path(history_path)
                legacy = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(legacy, dict):
                    raise ValueError("旧历史文件格式无效，无法清理书籍历史")
                if titles.intersection(legacy):
                    cleaned = {key: value for key, value in legacy.items() if key not in titles}
                    temporary = path.with_suffix(path.suffix + ".tmp")
                    temporary.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
                    temporary.replace(path)
            db.execute("DELETE FROM sessions WHERE book_id=?", (book_id,))
            db.execute("DELETE FROM preferences WHERE key=?", ("active:" + book_id,))
            db.execute("DELETE FROM preferences WHERE key='last_book' AND value=?", (book_id,))

    def migrate(self, history_path, books):
        """Import each uniquely matched legacy book once; leave source untouched."""
        history_path = Path(history_path)
        if not history_path.exists():
            return []
        legacy = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(legacy, dict):
            raise ValueError("旧历史文件格式无效")
        unmatched = []
        with self.connect() as db:
            for title, turns in legacy.items():
                matches = [b for b in books if b["name"] == title]
                if len(matches) != 1:
                    if turns:
                        unmatched.append(title)
                    continue
                key = "migrated:" + title
                if db.execute("SELECT 1 FROM preferences WHERE key=?", (key,)).fetchone():
                    continue
                if not isinstance(turns, list) or any(not isinstance(t, dict) or not isinstance(t.get("question"), str) or not isinstance(t.get("answer"), str) for t in turns):
                    raise ValueError("旧历史问答格式无效")
                if turns:
                    session_id = str(uuid.uuid4())
                    db.execute("INSERT INTO sessions(id,book_id,name) VALUES (?,?,?)", (session_id, matches[0]["id"], "历史会话"))
                    db.executemany("INSERT INTO turns(session_id,payload) VALUES (?,?)", [(session_id, json.dumps(t, ensure_ascii=False, allow_nan=False)) for t in turns])
                self._pref(db, key, matches[0]["id"])
        return unmatched
