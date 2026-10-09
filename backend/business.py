"""Explicit book-to-dataset mapping, independent of renamed display titles."""
import json
from .contracts import Error, missing, paginate


class Business:
    def __init__(self, database, root):
        self.database, self.root = database, root

    def dataset(self, user, bid, kind):
        with self.database.tx() as db:
            book = self.database.book(db, user, bid)
        dataset = book['dataset']
        # Dataset is written only by migration/provisioning, never by an API request.
        path = self.root / 'data' / f'{kind}_{dataset}.json'
        if not dataset or not path.is_file():
            raise Error(409, 'BUSINESS_DATA_UNAVAILABLE', '习题数据未就绪' if kind == 'exercises' else '此书籍尚未配置对应业务数据')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if kind == 'exercises' and (not isinstance(data, dict) or not isinstance(data.get('exercises'), list)):
                raise ValueError('Invalid question bank')
            return dataset, data
        except (OSError, ValueError):
            raise Error(503, 'DEPENDENCY_UNAVAILABLE', '习题数据未就绪' if kind == 'exercises' else '业务数据读取失败') from None

    @staticmethod
    def find(items, resource_id):
        result = next((x for x in items if str(x.get('id')) == resource_id), None)
        if result is None:
            missing()
        return result

    def characters(self, user, bid, family, page, page_size):
        _, data = self.dataset(user, bid, 'characters')
        return paginate([x for x in data.get('characters', []) if family is None or x.get('family') == family], page, page_size)

    def character(self, user, bid, cid):
        _, data = self.dataset(user, bid, 'characters')
        return self.find(data.get('characters', []), cid)

    def relations(self, user, bid, cid):
        _, data = self.dataset(user, bid, 'characters')
        self.find(data.get('characters', []), cid)
        names = {x['id']: x['name'] for x in data.get('characters', [])}
        items = []
        for row in data.get('relations', []):
            if cid in (row.get('from'), row.get('to')):
                target = row['to'] if row['from'] == cid else row['from']
                items.append({'source_id': row['from'], 'target_id': row['to'], 'target_name': names.get(target, target), 'relation': row['relation'], 'type': row.get('type')})
        return {'items': items}

    def families(self, user, bid):
        _, data = self.dataset(user, bid, 'characters')
        return {'items': sorted({x['family'] for x in data.get('characters', []) if x.get('family')})}

    def events(self, user, bid, cid, page, page_size):
        _, data = self.dataset(user, bid, 'characters')
        if cid:
            self.find(data.get('characters', []), cid)
        event_ids = {eid for row in data.get('character_events', []) if row.get('character_id') == cid for eid in row.get('events', [])}
        return paginate([x for x in data.get('events', []) if not cid or cid in x.get('characters', []) or x.get('id') in event_ids], page, page_size)

    def event(self, user, bid, eid):
        _, data = self.dataset(user, bid, 'characters')
        return self.find(data.get('events', []), eid)

    def graph(self, user, bid, scope, cid):
        dataset, data = self.dataset(user, bid, 'characters')
        if scope == 'character':
            if not cid:
                raise Error(422, 'VALIDATION_ERROR', 'character 模式必须提供 character_id')
            self.find(data.get('characters', []), cid)
        import character_service
        character_service.DATA_DIR = self.root / 'data'
        code = character_service.generate_mermaid_graph_family(dataset) if scope == 'family' else character_service.generate_mermaid_graph(cid if scope == 'character' else None, dataset)
        return {'format': 'mermaid', 'code': code}

    def exercises(self, user, bid, chapter, difficulty, page, page_size):
        _, data = self.dataset(user, bid, 'exercises')
        return paginate([{k: v for k, v in x.items() if k not in ('answer', 'explanation', 'source')} for x in data.get('exercises', []) if (chapter is None or x.get('chapter') == chapter) and (difficulty is None or x.get('difficulty') == difficulty)], page, page_size)

    def exercise(self, user, bid, eid):
        _, data = self.dataset(user, bid, 'exercises')
        return {k: v for k, v in self.find(data.get('exercises', []), eid).items() if k not in ('answer', 'explanation', 'source')}

    def chapters(self, user, bid):
        _, data = self.dataset(user, bid, 'exercises')
        return {'items': list(dict.fromkeys(x['chapter'] for x in data.get('exercises', []) if x.get('chapter')))}
