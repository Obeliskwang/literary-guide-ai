"""Book/file service independent of Streamlit; durable cross-storage cleanup."""
import hashlib
import json
import logging
import uuid
from pathlib import Path
from .contracts import Error, missing, paginate
from .database import now

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_COVER_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_CHUNKS = 30_000
ALLOWED_COVERS = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff', 'image/webp': b'RIFF'}


class Books:
    def __init__(self, database, adapter):
        self.database, self.adapter = database, adapter

    @staticmethod
    def file(row):
        return {k: row[k] for k in ('id', 'book_id', 'name', 'size_bytes', 'chunk_count', 'status', 'uploaded_at')}

    def describe(self, db, user, row, detail=False):
        files = [self.file(f) for f in db.execute('SELECT * FROM files WHERE book_id=? ORDER BY uploaded_at,id', (row['id'],))]
        result = {k: row[k] for k in ('id', 'name', 'author', 'category', 'description', 'created_at', 'visibility', 'status')}
        result['has_cover'] = bool(row['cover'])
        result.update(file_count=len(files), chunk_count=sum(f['chunk_count'] for f in files if f['status'] == 'ready'), writable=row['owner_id'] == user['id'] and (row['visibility'] == 'private' or user['role'] == 'admin'), capabilities={kind: bool(row['dataset'] and (self.adapter.root / 'data' / f'{kind}_{row["dataset"]}.json').is_file()) for kind in ('characters', 'exercises')})
        if detail:
            result['files'] = files
        return result

    def get(self, user, book_id):
        with self.database.tx() as db:
            return self.describe(db, user, self.database.book(db, user, book_id), True)

    def list(self, user, q, page, page_size):
        with self.database.tx() as db:
            rows = db.execute('SELECT * FROM books WHERE owner_id=? OR visibility=? ORDER BY created_at DESC,id', (user['id'], 'shared')).fetchall()
            items = [self.describe(db, user, row) for row in rows if not q or q.casefold() in row['name'].casefold()]
        return paginate(items, page, page_size)

    def create(self, user, name, key):
        with self.database.tx() as db:
            replay = self.database.reserve(db, user, 'books', key, {'name': name})
            if replay:
                return self.database.replay(replay)
            bid = str(uuid.uuid4())
            db.execute('INSERT INTO books(id,owner_id,name,created_at) VALUES (?,?,?,?)', (bid, user['id'], name, now()))
            result = self.describe(db, user, self.database.book(db, user, bid))
            self.database.finish(db, user, 'books', key, result)
        return result, 201, False

    def rename(self, user, book_id, name):
        return self.update(user, book_id, {'name': name})

    def update(self, user, book_id, changes):
        allowed = ('name', 'author', 'category', 'description')
        values = {key: changes[key] for key in allowed if key in changes and changes[key] is not None}
        if not values:
            return self.get(user, book_id)
        with self.database.tx() as db:
            self.database.book(db, user, book_id, True)
            if db.execute("SELECT 1 FROM idempotency i JOIN sessions s ON i.scope='question:'||s.id WHERE s.book_id=? AND i.state='generated'", (book_id,)).fetchone():
                raise Error(409, 'SESSION_BUSY', '书籍有回答待保存，请先完成原请求')
            holder = self.database.acquire(db, [(f'book:{book_id}', 'write')])
            assignments = ','.join(f'{key}=?' for key in values)
            db.execute(f'UPDATE books SET {assignments} WHERE id=?', (*values.values(), book_id))
            db.execute('DELETE FROM leases WHERE holder=?', (holder,))
        return self.get(user, book_id)

    def set_cover(self, user, book_id, raw, content_type):
        if not raw:
            raise Error(400, 'EMPTY_DOCUMENT', '封面文件为空')
        if len(raw) > MAX_COVER_BYTES:
            raise Error(413, 'FILE_TOO_LARGE', '封面不得超过 2 MiB')
        content_type = 'image/jpeg' if content_type == 'image/jpg' else content_type
        signature = ALLOWED_COVERS.get(content_type)
        if not signature or not raw.startswith(signature) or (content_type == 'image/webp' and raw[8:12] != b'WEBP'):
            raise Error(415, 'UNSUPPORTED_FILE_TYPE', '封面仅支持 PNG、JPEG、WEBP')
        with self.database.tx() as db:
            self.database.book(db, user, book_id, True)
            db.execute('UPDATE books SET cover=?,cover_mime=? WHERE id=?', (raw, content_type, book_id))
        return self.get(user, book_id)

    def cover(self, user, book_id):
        with self.database.tx() as db:
            row = self.database.book(db, user, book_id)
            if not row['cover']:
                missing()
            return bytes(row['cover']), row['cover_mime']

    @staticmethod
    def parse(raw, name):
        ext = Path(name).suffix.lower()
        if ext not in ('.txt', '.pdf', '.docx'):
            raise Error(415, 'UNSUPPORTED_FILE_TYPE', '仅支持 TXT、PDF、DOCX')
        if len(raw) > MAX_FILE_BYTES:
            raise Error(413, 'FILE_TOO_LARGE', '单文件不得超过 20 MiB')
        if not raw:
            raise Error(400, 'EMPTY_DOCUMENT', '文件为空')
        if ext == '.pdf' and not raw.startswith(b'%PDF-') or ext == '.docx' and not raw.startswith(b'PK'):
            raise Error(415, 'UNSUPPORTED_FILE_TYPE', '文件内容与扩展名不一致')
        if ext == '.txt' and (raw.startswith(b'%PDF-') or raw.startswith(b'PK')):
            raise Error(415, 'UNSUPPORTED_FILE_TYPE', '文件内容与扩展名不一致')
        try:
            from document_parser import parse_document
            text = parse_document(raw, name)
        except ImportError:
            raise Error(503, 'DEPENDENCY_UNAVAILABLE', '文档解析依赖不可用') from None
        except Exception:
            raise Error(400, 'INVALID_DOCUMENT', '文件损坏、加密或无法解析') from None
        if not text or not text.strip() or '\x00' in text:
            raise Error(400, 'EMPTY_DOCUMENT', '文件没有有效文本')
        if len(text) > MAX_TEXT_CHARS:
            raise Error(413, 'DOCUMENT_TOO_LARGE', '解析文本超过 200 万字符')
        return text

    def upload(self, user, book_id, name, raw, key):
        if not name or len(name) > 255 or '/' in name or '\\' in name or '\x00' in name or name in ('.', '..'):
            raise Error(422, 'VALIDATION_ERROR', '文件名无效，不允许目录路径')
        # Authorization precedes parsing or loading dependencies.
        with self.database.tx() as db:
            self.database.book(db, user, book_id, True)
        text = self.parse(raw, name)
        digest = hashlib.sha256(raw).hexdigest()
        scope = f'upload:{book_id}'
        with self.database.tx() as db:
            book = self.database.book(db, user, book_id, True)
            replay = self.database.reserve(db, user, scope, key, {'name': name, 'hash': digest})
            if replay:
                return self.database.replay(replay)
            if book['status'] != 'ready':
                raise Error(409, 'BOOK_NOT_READY', '书籍仍在恢复或删除中')
            holder = self.database.acquire(db, [(f'book:{book_id}', 'write')])
            existing = db.execute('SELECT * FROM files WHERE book_id=? AND content_hash=?', (book_id, digest)).fetchone()
            if existing and existing['status'] == 'ready':
                result = self.file(existing)
                self.database.finish(db, user, scope, key, result, 200)
                db.execute('DELETE FROM leases WHERE holder=?', (holder,))
                return result, 200, False
            if existing:
                raise Error(409, 'BOOK_NOT_READY', '同内容文件等待清理，请稍后重试')
            fid = str(uuid.uuid4())
            db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)', (fid, book_id, name, len(raw), 0, digest, 'uploading', now()))
            db.execute("UPDATE books SET status='processing' WHERE id=?", (book_id,))
        try:
            count = self.adapter.index(book_id, fid, name, text)
            if not 0 < count <= MAX_CHUNKS:
                raise Error(413, 'DOCUMENT_TOO_LARGE', '分块数量无效或超过 30000')
            with self.database.tx() as db:
                db.execute("UPDATE files SET chunk_count=?,status='ready' WHERE id=?", (count, fid))
                db.execute("UPDATE books SET status='ready' WHERE id=?", (book_id,))
                result = self.file(db.execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone())
                self.database.finish(db, user, scope, key, result)
            return result, 201, False
        except Exception as exc:
            error = exc if isinstance(exc, Error) else Error(503, 'DEPENDENCY_UNAVAILABLE', '索引建立失败，请检查嵌入服务')
            with self.database.tx() as db:
                db.execute("UPDATE files SET status='cleanup' WHERE id=?", (fid,))
                self.database.finish(db, user, scope, key, {'code': error.code, 'message': error.message}, error.status, 'failed')
            try:
                self.cleanup_file(book_id, fid)
            except Exception:
                logger.error('Upload compensation pending: book_id=%s file_id=%s', book_id, fid)
            raise error from None
        finally:
            self.database.release(holder)

    def cleanup_file(self, book_id, file_id):
        self.adapter.remove_file(book_id, file_id)
        with self.database.tx() as db:
            db.execute('DELETE FROM files WHERE id=?', (file_id,))
            if not db.execute("SELECT 1 FROM files WHERE book_id=? AND status!='ready'", (book_id,)).fetchone():
                db.execute("UPDATE books SET status='ready' WHERE id=? AND status!='deleting'", (book_id,))

    def delete_file(self, user, book_id, file_id):
        tomb = f'{book_id}/{file_id}'
        with self.database.tx() as db:
            self.database.book(db, user, book_id, True)
            if self.database.deleted(db, user, 'file', tomb):
                return {'deleted': True, 'book_id': book_id, 'remaining_chunk_count': self.describe(db, user, self.database.book(db, user, book_id))['chunk_count']}
            row = db.execute('SELECT * FROM files WHERE id=? AND book_id=?', (file_id, book_id)).fetchone()
            if not row:
                missing()
            holder = self.database.acquire(db, [(f'book:{book_id}', 'write')])
            db.execute("UPDATE files SET status='deleting' WHERE id=?", (file_id,))
            db.execute("UPDATE books SET status='processing' WHERE id=?", (book_id,))
            self.database.tombstone(db, user, 'file-pending', tomb)
        try:
            self.cleanup_file(book_id, file_id)
            with self.database.tx() as db:
                self.database.tombstone(db, user, 'file', tomb)
            return {'deleted': True, 'book_id': book_id, 'remaining_chunk_count': self.get(user, book_id)['chunk_count']}
        except Exception:
            raise Error(503, 'DEPENDENCY_UNAVAILABLE', '文件删除待恢复，请重试') from None
        finally:
            self.database.release(holder)

    def cleanup_book(self, book_id, user):
        self.adapter.remove_book(book_id)
        with self.database.tx() as db:
            self.database.tombstone(db, user, 'book', book_id)
            for row in db.execute('SELECT id,owner_id FROM sessions WHERE book_id=?', (book_id,)):
                self.database.tombstone(db, {'id': row['owner_id']}, 'session', row['id'])
                from .database import dump
                db.execute("UPDATE idempotency SET state='failed',result=?,status=410 WHERE owner_id=? AND scope=?", (dump({'code': 'RESOURCE_REMOVED', 'message': '原问答历史已删除'}), row['owner_id'], f'question:{row["id"]}'))
            db.execute('DELETE FROM books WHERE id=?', (book_id,))
            self.database.prune_preferences(db)

    def delete(self, user, book_id):
        with self.database.tx() as db:
            if self.database.deleted(db, user, 'book', book_id):
                return {'deleted': True}
            self.database.book(db, user, book_id, True)
            if db.execute("SELECT 1 FROM idempotency i JOIN sessions s ON i.scope='question:'||s.id WHERE s.book_id=? AND i.state='generated'", (book_id,)).fetchone():
                raise Error(409, 'SESSION_BUSY', '书籍有回答待保存，请先完成原请求')
            holder = self.database.acquire(db, [(f'book:{book_id}', 'write')])
            db.execute("UPDATE books SET status='deleting' WHERE id=?", (book_id,))
        try:
            self.cleanup_book(book_id, user)
            return {'deleted': True}
        except Exception:
            raise Error(503, 'DEPENDENCY_UNAVAILABLE', '书籍删除待恢复，请重试') from None
        finally:
            self.database.release(holder)

    def recover(self):
        with self.database.tx() as db:
            books = [dict(r) for r in db.execute("SELECT * FROM books WHERE status='deleting'")]
            files = [dict(r) for r in db.execute("SELECT * FROM files WHERE status IN ('uploading','cleanup','deleting')")]
        for book in books:
            try:
                self.cleanup_book(book['id'], {'id': book['owner_id']})
            except Exception:
                logger.error('Book cleanup pending: id=%s', book['id'])
        for file in files:
            if any(book['id'] == file['book_id'] for book in books):
                continue
            try:
                self.cleanup_file(file['book_id'], file['id'])
                with self.database.tx() as db:
                    tomb = f'{file["book_id"]}/{file["id"]}'
                    db.execute("INSERT OR IGNORE INTO tombstones SELECT owner_id,'file',id FROM tombstones WHERE kind='file-pending' AND id=?", (tomb,))
            except Exception:
                logger.error('File cleanup pending: id=%s', file['id'])
        with self.database.tx() as db:
            db.execute("UPDATE idempotency SET state='failed',status=503,result=? WHERE state='pending' AND scope LIKE 'upload:%'", (json.dumps({'code': 'UPLOAD_INTERRUPTED', 'message': '上传中断，清理完成后请发起新上传'}),))
