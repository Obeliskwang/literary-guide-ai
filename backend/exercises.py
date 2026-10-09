"""Server-owned self tests, immutable grading snapshots and per-user history."""
import json
import uuid
from .contracts import Error, missing, paginate
from .database import dump, now


class SelfTests:
    def __init__(self, database, business):
        self.database, self.business = database, business

    def start(self, user, bid, payload, key):
        _, data = self.business.dataset(user, bid, 'exercises')
        with self.database.tx() as db:
            self.database.book(db, user, bid)
            replay = self.database.reserve(db, user, 'exercise-start:' + bid, key, payload)
            if replay:
                return self.database.replay(replay)
            chapters = set(payload['chapters'])
            rows = data.get('exercises', [])
            if not chapters.issubset({q.get('chapter') for q in rows}):
                raise Error(422, 'VALIDATION_ERROR', '所选章节不存在')
            rows = [q for q in rows if q.get('chapter') in chapters and (not payload['difficulty'] or q.get('difficulty') == payload['difficulty'])]
            if not rows:
                raise Error(409, 'EXERCISES_UNAVAILABLE', '所选章节没有习题')
            if len({q['id'] for q in rows}) != len(rows) or any(type(q.get('answer')) is not int or not 0 <= q['answer'] < len(q.get('options', [])) for q in rows):
                raise Error(409, 'EXERCISES_UNAVAILABLE', '习题数据未就绪')
            aid = uuid.uuid4().hex
            db.execute('INSERT INTO exercise_attempts VALUES (?,?,?,?,?,NULL)', (aid, user['id'], bid, now(), dump(rows)))
            result = {'id': aid, 'questions': [{k: q[k] for k in ('id', 'chapter', 'question', 'options', 'difficulty') if k in q} for q in rows]}
            self.database.finish(db, user, 'exercise-start:' + bid, key, result)
            return result, 201, False

    def submit(self, user, bid, aid, answers):
        with self.database.tx() as db:
            self.database.book(db, user, bid)
            row = db.execute('SELECT * FROM exercise_attempts WHERE id=? AND owner_id=? AND book_id=?', (aid, user['id'], bid)).fetchone()
            if not row:
                missing()
            questions = json.loads(row['questions'])
            if set(answers) != {q['id'] for q in questions} or any(answers.get(q['id']) is None for q in questions):
                raise Error(422, 'ANSWERS_REQUIRED', '请先选择答案')
            if any(type(answers[q['id']]) is not int or not 0 <= answers[q['id']] < len(q['options']) for q in questions):
                raise Error(422, 'VALIDATION_ERROR', '答案选项无效')
            if row['result']:
                result = json.loads(row['result'])
                if any(answers[q['id']] != q['selected'] for q in result['questions']):
                    raise Error(409, 'ATTEMPT_SUBMITTED', '本次自测已提交，请开始新的自测')
                return result
            graded = [dict(q, selected=answers[q['id']], correct=answers[q['id']] == q['answer'], source=q.get('source') or '原著出处待补充') for q in questions]
            correct = sum(q['correct'] for q in graded)
            result = {'id': aid, 'submitted_at': now(), 'total': len(graded), 'correct': correct, 'accuracy': round(correct / len(graded) * 100, 2), 'questions': graded}
            db.execute('UPDATE exercise_attempts SET result=? WHERE id=?', (dump(result), aid))
            return result

    def records(self, user, bid):
        with self.database.tx() as db:
            self.database.book(db, user, bid)
            return [json.loads(r['result']) for r in db.execute('SELECT result FROM exercise_attempts WHERE owner_id=? AND book_id=? AND result IS NOT NULL ORDER BY created_at DESC,id DESC', (user['id'], bid))]

    def history(self, user, bid, page, page_size):
        return paginate(self.records(user, bid), page, page_size)

    def stats(self, user, bid):
        records = self.records(user, bid)
        chapters = {}
        for record in records:
            for q in record['questions']:
                item = chapters.setdefault(q['chapter'], {'chapter': q['chapter'], 'total': 0, 'correct': 0})
                item['total'] += 1
                item['correct'] += int(q['correct'])
        total = sum(r['total'] for r in records)
        correct = sum(r['correct'] for r in records)
        for item in chapters.values():
            item['accuracy'] = round(item['correct'] / item['total'] * 100, 2)
        return {'attempts': len(records), 'total': total, 'correct': correct, 'accuracy': round(correct / total * 100, 2) if total else 0, 'chapters': list(chapters.values()), 'trend': [{k: r[k] for k in ('id', 'submitted_at', 'accuracy')} for r in reversed(records)]}
