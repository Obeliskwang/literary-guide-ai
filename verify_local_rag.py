"""Optional real local Ollama acceptance; creates and cleans only its own test book."""
import json
import uuid
from run_local import ROOT  # Load project-local dependencies.
from api_client import APIClient


def main():
    from config import OLLAMA_LLM_MODEL
    client = APIClient()
    try:
        tags = client.transport.get('http://localhost:11434/api/tags', timeout=5).json()
        available = {row['name'] for row in tags.get('models', [])}
        if OLLAMA_LLM_MODEL not in available:
            print(json.dumps({'status': 'not_ready', 'reason': '项目配置的本地回答模型未安装', 'model': OLLAMA_LLM_MODEL}, ensure_ascii=False))
            return 1
    except Exception:
        print(json.dumps({'status': 'not_ready', 'reason': '无法连接本地 Ollama'}, ensure_ascii=False))
        return 1
    tokens = client.request('POST', '/api/auth/login', json={'username': 'demo', 'password': 'Demo@123456'})
    client.access_token, client.refresh_token = tokens['access_token'], tokens['refresh_token']
    bid = None
    try:
        client.request('PUT', '/api/auth/model-settings', json={'mode': 'ollama', 'model': OLLAMA_LLM_MODEL, 'base_url': 'http://localhost:11434'})
        book = client.request('POST', '/api/books', json={'name': 'API验收临时书-' + uuid.uuid4().hex[:6]}, key=str(uuid.uuid4()))
        bid = book['id']
        content = '第一回 取经团队\n孙悟空是唐僧的徒弟。孙悟空使用金箍棒，保护唐僧西行取经。唐僧的徒弟还有猪八戒和沙僧。\n'
        file = client.request('POST', f'/api/books/{bid}/files', files={'file': ('acceptance.txt', content.encode('utf-8'))}, key=str(uuid.uuid4()))
        session = client.request('POST', f'/api/books/{bid}/sessions', json={}, key=str(uuid.uuid4()))
        sid, key = session['id'], str(uuid.uuid4())
        path, body = f'/api/sessions/{sid}/questions', {'question': '孙悟空使用什么武器？'}
        turn = client.request('POST', path, json=body, key=key)
        replay = client.request('POST', path, json=body, key=key)
        history = client.request('GET', f'/api/sessions/{sid}/messages')
        assert turn['turn_id'] == replay['turn_id'] and history['total'] == 1
        assert turn['answer'] and turn['sources'] and not turn['rejected']
        print(json.dumps({'status': 'passed', 'model': OLLAMA_LLM_MODEL, 'chunks': file['chunk_count'], 'saved_turns': history['total'], 'sources': len(turn['sources']), 'same_key_same_turn': True, 'answer_mentions_weapon': '金箍棒' in turn['answer']}, ensure_ascii=False, indent=2))
        return 0
    finally:
        try:
            if bid:
                client.request('DELETE', f'/api/books/{bid}')
        finally:
            client.request('POST', '/api/auth/logout', json={'refresh_token': client.refresh_token}, refresh=False)


if __name__ == '__main__':
    raise SystemExit(main())
