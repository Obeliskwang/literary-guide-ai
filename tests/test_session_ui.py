import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest import TestCase
from unittest.mock import MagicMock, patch
from session_store import SessionStore


class State(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


class SessionUITests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SessionStore(Path(self.tmp.name) / 'db.sqlite3')
        self.st = MagicMock()
        self.st.session_state = State(current_book_id='a')
        self.st.button.return_value = False
        self.st.form_submit_button.return_value = False
        self.st.selectbox.side_effect = lambda label, ids, **kw: ids[kw['index']]
        spec = importlib.util.spec_from_file_location('session_ui_tested', Path(__file__).resolve().parents[1] / 'session_ui.py')
        self.ui = importlib.util.module_from_spec(spec)
        self.books = MagicMock()
        self.books.load_books_metadata.return_value = [{'id': 'a', 'name': 'A'}]
        self.book_manager = MagicMock()
        with patch.dict(sys.modules, {'streamlit': self.st, 'utils': self.books, 'book_manager': self.book_manager}):
            spec.loader.exec_module(self.ui)

    def test_book_switch(self):
        a = self.store.create('a')
        self.store.append(a, 'a', {'question': 'A', 'answer': 'AA'})
        b = self.store.create('b')
        self.store.append(b, 'b', {'question': 'B', 'answer': 'BB'})
        self.ui.render_sessions(self.store)
        self.assertEqual(self.st.session_state.chat_history[0]['question'], 'A')
        self.st.session_state.current_book_id = 'b'
        self.ui.render_sessions(self.store)
        self.assertEqual(self.st.session_state.chat_history[0]['question'], 'B')

    def test_session_switch(self):
        a = self.store.create('a')
        self.store.append(a, 'a', {'question': 'old', 'answer': 'answer'})
        b = self.store.create('a')
        self.st.selectbox.side_effect = lambda *args, **kw: a
        self.ui.render_sessions(self.store)
        self.assertEqual(self.st.session_state.chat_history[0]['question'], 'old')
        self.st.selectbox.side_effect = lambda *args, **kw: b
        self.ui.render_sessions(self.store)
        self.assertEqual(self.st.session_state.chat_history, [])

    def test_restart_once(self):
        self.store.create('a')
        self.ui.restore_book(self.store)
        self.ui.restore_book(self.store)
        self.book_manager.select_book.assert_called_once_with('a')

    def test_no_book(self):
        self.st.session_state.current_book_id = ''
        self.ui.render_sessions(self.store)
        self.assertIsNone(self.st.session_state.active_session_id)
