import json
import tempfile
import unittest
from pathlib import Path

from session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sessions.sqlite3"
        self.store = SessionStore(self.path)
        self.turn = {"question": "是谁？", "answer": "孙悟空", "sources": [{"text": "原文", "metadata": {"chapter": "第一回"}}], "rejected": False}

    def test_crud_restart_and_cascade(self):
        first = self.store.create("book-a")
        second = self.store.create("book-a", "人物分析")
        self.store.append(first, "book-a", self.turn)
        self.store.select(first, "book-a")
        self.store.rename(first, "book-a", " 新名字 ")
        reopened = SessionStore(self.path)
        self.assertEqual(reopened.active("book-a"), first)
        self.assertEqual(reopened.preference("last_book"), "book-a")
        self.assertEqual(reopened.history(first, "book-a"), [self.turn])
        self.assertEqual(reopened.history(second, "book-a"), [])
        self.assertEqual(reopened.list("book-a")[0]["name"], "新名字")
        reopened.delete(first, "book-a")
        self.assertEqual(reopened.active("book-a"), second)
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 0)

    def test_isolation_and_invalid_operations(self):
        sid = self.store.create("a")
        for operation in [lambda: self.store.history(sid, "b"), lambda: self.store.append(sid, "b", self.turn), lambda: self.store.delete(sid, "b"), lambda: self.store.select(sid, "b"), lambda: self.store.rename(sid, "b", "name"), lambda: self.store.clear(sid, "b")]:
            with self.assertRaises(ValueError):
                operation()
        for name in ["", "  ", "x" * 101]:
            with self.assertRaises(ValueError):
                self.store.rename(sid, "a", name)
        with self.assertRaises(ValueError):
            self.store.append(sid, "a", {**self.turn, "error": "failed"})
        self.assertEqual(self.store.history(sid, "a"), [])

    def test_order_clear_and_deleted_last(self):
        sid = self.store.create("a")
        self.store.append(sid, "a", self.turn)
        self.store.append(sid, "a", {**self.turn, "question": "然后呢"})
        self.assertEqual([t["question"] for t in self.store.history(sid, "a")], ["是谁？", "然后呢"])
        self.store.clear(sid, "a")
        self.assertEqual(self.store.history(sid, "a"), [])
        self.store.delete(sid, "a")
        self.assertIsNone(self.store.active("a"))

    def test_migration_idempotent_and_no_resurrection(self):
        source = Path(self.tmp.name) / "legacy.json"
        source.write_text(json.dumps({"西游记": [self.turn], "不存在": [self.turn], "重名": [self.turn]}), encoding="utf-8")
        original = source.read_bytes()
        books = [{"id": "a", "name": "西游记"}, {"id": "b", "name": "重名"}, {"id": "c", "name": "重名"}]
        self.assertEqual(self.store.migrate(source, books), ["不存在", "重名"])
        self.store.migrate(source, books)
        sessions = self.store.list("a")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(self.store.history(sessions[0]["id"], "a"), [self.turn])
        self.store.delete(sessions[0]["id"], "a")
        self.store.migrate(source, books)
        self.assertEqual(self.store.list("a"), [])
        self.assertEqual(source.read_bytes(), original)

    def test_bad_migration_rolls_back(self):
        source = Path(self.tmp.name) / "legacy.json"
        source.write_text(json.dumps({"good": [self.turn], "bad": [{}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.migrate(source, [{"id": "a", "name": "good"}, {"id": "b", "name": "bad"}])
        self.assertEqual(self.store.list("a"), [])

    def test_delete_book_removes_all_history_and_legacy_after_rename(self):
        source = Path(self.tmp.name) / "legacy.json"
        source.write_text(json.dumps({"old-name": [self.turn], "other": [self.turn]}), encoding="utf-8")
        self.store.migrate(source, [{"id": "a", "name": "old-name"}, {"id": "b", "name": "other"}])
        sid = self.store.create("a")
        self.store.append(sid, "a", self.turn)
        self.store.delete_book("a", source, "new-name")
        reopened = SessionStore(self.path)
        self.assertEqual(reopened.list("a"), [])
        self.assertIsNone(reopened.preference("active:a"))
        self.assertIsNone(reopened.preference("last_book"))
        self.assertEqual(list(json.loads(source.read_text(encoding="utf-8"))), ["other"])
        self.assertEqual(len(reopened.list("b")), 1)
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 1)
        reopened.migrate(source, [{"id": "a", "name": "old-name"}, {"id": "b", "name": "other"}])
        self.assertEqual(reopened.list("a"), [])

    def test_invalid_legacy_aborts_book_history_delete(self):
        sid = self.store.create("a")
        self.store.append(sid, "a", self.turn)
        source = Path(self.tmp.name) / "legacy.json"
        source.write_text("invalid", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.delete_book("a", source, "name")
        self.assertEqual(self.store.history(sid, "a"), [self.turn])



if __name__ == "__main__":
    unittest.main()
