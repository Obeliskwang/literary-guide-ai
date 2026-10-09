"""Safe local HTTP check: no remote model call, no secrets printed."""
import json
import os
import requests


def main():
    base = os.getenv('LITERARY_API_URL', 'http://127.0.0.1:8000').rstrip('/')
    session = requests.Session()
    session.trust_env = False
    report = {}
    def get(path, headers=None):
        response = session.get(base + path, headers=headers, timeout=(5, 30))
        return response.status_code, response.json()
    for path in ('/health/live', '/health/ready', '/health/ready?check_models=true'):
        status, result = get(path)
        report[path] = {'status': status, 'code': result['code']}
    report['openapi_paths'] = len(get('/openapi.json')[1]['paths'])
    tokens = session.post(base + '/api/auth/login', json={'username': 'demo', 'password': 'Demo@123456'}, timeout=10).json()['data']
    try:
        headers = {'Authorization': 'Bearer ' + tokens['access_token']}
        status, result = get('/api/books?page_size=100', headers)
        books = result['data']['items']
        report['books'] = {'status': status, 'total': result['data']['total']}
        sessions, turns, business = 0, 0, []
        for book in books:
            bid = book['id']
            _, value = get(f'/api/books/{bid}/sessions?page_size=100', headers)
            sessions += value['data']['total']
            for conversation in value['data']['items']:
                _, history = get(f'/api/sessions/{conversation["id"]}/messages', headers)
                turns += history['data']['total']
            if book['capabilities']['characters']:
                code, value = get(f'/api/books/{bid}/characters', headers)
                business.append({'kind': 'characters', 'status': code, 'total': value['data']['total']})
            if book['capabilities']['exercises']:
                code, value = get(f'/api/books/{bid}/exercises', headers)
                business.append({'kind': 'exercises', 'status': code, 'total': value['data']['total']})
        report.update(sessions=sessions, turns=turns, business=business)
    finally:
        session.post(base + '/api/auth/logout', json={'refresh_token': tokens['refresh_token']}, timeout=10)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
