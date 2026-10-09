"""Lazy adapter to the existing RAG stack; tests inject a deterministic adapter."""
import os
from contextlib import contextmanager
from pathlib import Path
from .contracts import Error

ROOT = Path(__file__).resolve().parents[1]


class RagAdapter:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def module(self):
        import rag
        rag.PERSIST_ROOT = self.root / 'chroma_db'
        return rag

    def ready(self):
        from ollama_check import ensure_ollama_models
        ensure_ollama_models(embedding_only=True)

    def index(self, book_id, file_id, name, text):
        module = self.module()
        docs = module.split_text_by_lines(module.clean_text(text), source_format=Path(name).suffix.lstrip('.'))
        if not 0 < len(docs) <= 30_000:
            raise Error(413, 'DOCUMENT_TOO_LARGE', '分块数量无效或超过 30000')
        _, count = module.create_vector_store(text, book_id, file_id, name)
        return count

    def remove_file(self, book_id, file_id):
        # Delete does not require contacting the embedding provider.
        import chromadb
        path = self.root / 'chroma_db' / f'book_{book_id}'
        if not path.exists():
            return
        client = chromadb.PersistentClient(path=str(path))
        for collection in client.list_collections():
            collection.delete(where={'file_id': file_id})

    def remove_book(self, book_id):
        # Chroma owns open SQLite handles on Windows; remove collections, not open files.
        import chromadb
        path = self.root / 'chroma_db' / f'book_{book_id}'
        if path.exists():
            client = chromadb.PersistentClient(path=str(path))
            for collection in client.list_collections():
                client.delete_collection(collection.name)

    def answer(self, book_id, question, history, settings):
        from agent import generate_answer
        store = self.module().get_vector_store_by_book(book_id)
        if store is None or store._collection.count() == 0:
            raise Error(409, 'BOOK_NOT_READY', '书籍索引尚未准备好')
        return generate_answer(store, question, conversation_history=history, chat_settings=settings)

    def choose_tool(self, question, settings, tools):
        from chat_backend import choose_tool
        return choose_tool(settings, question, tools)


@contextmanager
def process_lock(path):
    """One API process per database: prevents restart recovery stealing live leases."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    handle.seek(0)
    if not handle.read(1):
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('此数据库已有后端进程运行；请使用单 worker') from None
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == 'nt':
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
