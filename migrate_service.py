"""Explicit, backed-up migration. Never automatically claim legacy user data."""
import argparse
import json
import re
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from backend.database import Database, dump, now
from backend.runtime import ROOT, process_lock
from auth_service import AuthService


def timestamp(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        from datetime import timedelta
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.astimezone(timezone.utc).isoformat()


def read_db(path):
    db = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def migrate(root=ROOT, data_dir=None, owner='demo'):
    root = Path(root).resolve()
    target = Path(data_dir or root / 'data').resolve()
    with process_lock(target / 'api.lock'):
        database = Database(target / 'service.sqlite3')
        previous_report = None
        with database.tx() as db:
            previous = db.execute("SELECT details FROM migrations WHERE name='legacy-v1'").fetchone()
            if previous:
                previous_report = json.loads(previous[0])
        if previous_report is not None:
            return dict(previous_report, already_migrated=True, index_reconciliation=reconcile_counts(database, root, Path(previous_report['backup'])))
        metadata_path = root / 'data/books.json'
        books = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else []
        if not isinstance(books, list) or any(not isinstance(b, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', b.get('id', '')) or not isinstance(b.get('name'), str) for b in books):
            raise ValueError('旧书籍数据格式无效，源文件未修改')
        history_path = root / 'chat_history_cache.json'
        history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {}
        if not isinstance(history, dict):
            raise ValueError('旧历史格式无效')
        auth = AuthService(target / 'auth.sqlite3')
        auth.initialize_demo_users()
        with auth.connect() as db:
            user = db.execute('SELECT id FROM users WHERE username=?', (owner,)).fetchone()
        if not user:
            raise ValueError('迁移归属用户不存在')
        backup = target / 'migration_backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup.mkdir(parents=True)
        for source in (metadata_path, history_path, root / 'data/sessions.sqlite3', target / 'auth.sqlite3', target / 'service.sqlite3'):
            if not source.exists():
                continue
            if source.suffix == '.sqlite3':
                with closing(read_db(source)) as src, closing(sqlite3.connect(backup / source.name)) as dst:
                    src.backup(dst)
            else:
                shutil.copy2(source, backup / source.name)
        legacy_path = root / 'data/sessions.sqlite3'
        legacy_sessions, legacy_turns, preferences = [], [], {}
        if legacy_path.exists():
            with closing(read_db(legacy_path)) as old:
                legacy_sessions = [dict(r) for r in old.execute('SELECT * FROM sessions')]
                legacy_turns = [dict(r) for r in old.execute('SELECT * FROM turns ORDER BY id')]
                preferences = dict(old.execute('SELECT key,value FROM preferences'))
        report = {'owner': owner, 'books': len(books), 'sessions': 0, 'turns': 0, 'unmatched_history': [], 'backup': str(backup), 'naive_timestamp_timezone': 'Asia/Shanghai'}
        with database.tx() as db:
            if db.execute('SELECT 1 FROM books').fetchone():
                raise ValueError('目标库已有业务数据，请先迁移到空库；不会覆盖现有资源')
            for book in books:
                bid = book['id']
                dataset = book['name'] if any((root / 'data' / f'{kind}_{book["name"]}.json').is_file() for kind in ('characters', 'exercises')) else None
                # Mapping is an allow-listed local file stem, not a client-controlled path.
                if dataset and ('/' in dataset or '\\' in dataset or dataset in ('.', '..')):
                    raise ValueError('旧业务映射名称不安全')
                db.execute(
                    'INSERT INTO books(id,owner_id,name,created_at,visibility,dataset,status) VALUES (?,?,?,?,?,?,?)',
                    (bid, user['id'], book['name'], timestamp(book.get('created_at')), 'private', dataset, 'ready'),
                )
                for file in book.get('files', []):
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', file['id']):
                        raise ValueError('旧文件标识无效')
                    db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)', (file['id'], bid, file['name'], None, file.get('chunk_count', 0), None, 'ready', timestamp(file.get('uploaded_at'))))
            book_ids = {b['id'] for b in books}
            sids = set()
            for session in legacy_sessions:
                if session['book_id'] not in book_ids:
                    raise ValueError('旧会话关联书籍缺失，迁移已回滚')
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)', (session['id'], user['id'], session['book_id'], session['name'], timestamp(session['created_at']), timestamp(session['updated_at'])))
                sids.add(session['id'])
                report['sessions'] += 1
            for row in legacy_turns:
                if row['session_id'] not in sids:
                    raise ValueError('旧问答会话缺失')
                turn = clean_turn(json.loads(row['payload']))
                turn['turn_id'] = row['id']
                db.execute('INSERT INTO turns VALUES (?,?,?)', (row['id'], row['session_id'], dump(turn)))
                report['turns'] += 1
            for title, turns in history.items():
                if 'migrated:' + title in preferences or not turns:
                    continue
                matches = [b for b in books if b['name'] == title]
                if len(matches) != 1:
                    report['unmatched_history'].append(title)
                    continue
                sid, ts = str(uuid.uuid4()), now()
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)', (sid, user['id'], matches[0]['id'], '历史会话', ts, ts))
                report['sessions'] += 1
                if not isinstance(turns, list):
                    raise ValueError('旧问答格式无效')
                for turn in turns:
                    normalized = clean_turn(turn)
                    cursor = db.execute('INSERT INTO turns(session_id,payload) VALUES (?,?)', (sid, dump(normalized)))
                    normalized['turn_id'] = cursor.lastrowid
                    db.execute('UPDATE turns SET payload=? WHERE id=?', (dump(normalized), cursor.lastrowid))
                    report['turns'] += 1
            pref = {'last_book_id': preferences.get('last_book'), 'active_session_by_book': {k.removeprefix('active:'): v for k, v in preferences.items() if k.startswith('active:')}}
            db.execute('INSERT INTO preferences VALUES (?,?)', (user['id'], dump(pref)))
            database.prune_preferences(db)
            db.execute('INSERT INTO migrations VALUES (?,?,?)', ('legacy-v1', now(), dump(report)))
        (backup / 'migration-report.json').write_text(dump(report), encoding='utf-8')
        return dict(report, index_reconciliation=reconcile_counts(database, root, backup))


def reconcile_counts(database, root, backup):
    """Read legacy Chroma metadata without embedding calls or mutating old indexes."""
    with database.tx() as db:
        existing = db.execute("SELECT details FROM migrations WHERE name='legacy-index-counts-v1'").fetchone()
        if existing:
            return json.loads(existing[0])
        files = [dict(row) for row in db.execute('SELECT * FROM files WHERE size_bytes IS NULL')]
    backup.mkdir(parents=True, exist_ok=True)
    with closing(read_db(database.path.resolve())) as src, closing(sqlite3.connect(backup / 'service.before-index-counts.sqlite3')) as dst:
        src.backup(dst)
    counts, missing_files = [], 0
    for file in files:
        index = root / 'chroma_db' / ('book_' + file['book_id']) / 'chroma.sqlite3'
        count = 0
        if index.exists():
            with closing(read_db(index.resolve())) as db:
                # Schema verified against this project's persisted Chroma SQLite.
                count = db.execute('SELECT COUNT(*) FROM embedding_metadata WHERE key=? AND string_value=?', ('file_id', file['id'])).fetchone()[0]
        if not count:
            missing_files += 1
        counts.append((count, 'ready' if count else 'legacy_unindexed', file['id']))
    report = {'files': len(files), 'chunks': sum(row[0] for row in counts), 'unindexed_files': missing_files}
    with database.tx() as db:
        db.executemany('UPDATE files SET chunk_count=?,status=? WHERE id=?', counts)
        db.execute('INSERT INTO migrations VALUES (?,?,?)', ('legacy-index-counts-v1', now(), dump(report)))
    return report


def clean_turn(turn):
    if not isinstance(turn, dict) or not isinstance(turn.get('question'), str) or not isinstance(turn.get('answer'), str):
        raise ValueError('旧问答字段无效')
    result = {k: turn[k] for k in ('question', 'answer', 'rejected', 'soft_reject', 'min_distance') if k in turn}
    result['created_at'] = timestamp(turn.get('created_at'))
    result['sources'] = [{'text': str(s.get('text', '')), 'metadata': {k: s.get('metadata', {}).get(k) for k in ('file_id', 'file_name', 'chapter')}, 'distance': s.get('distance')} for s in turn.get('sources', [])]
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='备份并迁移旧数据，归属由 --owner 明确指定')
    parser.add_argument('--owner', required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.root, args.data_dir, args.owner), ensure_ascii=False, indent=2))
