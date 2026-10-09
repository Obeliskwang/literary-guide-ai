"""Export reviewed route/field contracts from the actual OpenAPI, without starting services."""
import json
from pathlib import Path
from run_local import ROOT
from api import create_app


def export():
    spec = create_app().openapi()
    output = ROOT.parent / '文档'
    output.mkdir(exist_ok=True)
    (output / 'P0_OpenAPI.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    schemas = spec['components']['schemas']
    def sample(schema, name='', depth=0):
        if depth > 10:
            return None
        if '$ref' in schema:
            return sample(schemas[schema['$ref'].split('/')[-1]], name, depth+1)
        if 'default' in schema and not (name == 'data' and 'anyOf' in schema):
            return schema['default']
        if 'enum' in schema:
            if name == 'mode' and 'ollama' in schema['enum']:
                return 'ollama'
            return schema['enum'][0]
        if 'anyOf' in schema:
            return sample(next((s for s in schema['anyOf'] if s.get('type') != 'null'), schema['anyOf'][0]), name, depth+1)
        kind = schema.get('type')
        if kind == 'object':
            return {key: sample(value, key, depth+1) for key, value in schema.get('properties', {}).items()}
        if kind == 'array':
            return [sample(schema.get('items', {}), name, depth+1)]
        if kind in ('integer', 'number'):
            return schema.get('minimum', 1)
        if kind == 'boolean':
            return False
        return {'name': '示例书籍', 'question': '孙悟空使用什么武器？', 'username': 'demo', 'password': 'Demo@123456', 'token_type': 'Bearer', 'nickname': '演示用户', 'role': 'user', 'request_id': 'example-request-id', 'created_at': '2026-10-07T13:00:00+00:00', 'updated_at': '2026-10-07T13:00:00+00:00', 'api_key': '<仅在首次远程配置时填入密钥>', 'refresh_token': '<登录返回的 refresh_token>', 'access_token': '<登录返回的 access_token>', 'base_url': 'http://localhost:11434', 'model': 'qwen2.5:0.5b-instruct', 'status': 'ready', 'visibility': 'private', 'id': '<资源ID>', 'book_id': '<书籍ID>', 'last_book_id': None}.get(name, 'string')
    lines = ['# P0 FastAPI 接口契约定稿', '', '本文件从实际路由和 OpenAPI 导出；示例用于说明结构，不是生产请求结果。具体业务动作、幂等、权限与边界规则见需求审阅稿及交付验收说明。', '', '所有 `/api` 业务路由使用统一响应。创建、上传和问答必传 `Idempotency-Key`；同键重放返回 `Idempotency-Replayed: true`。鉴权 Bearer 凭证在 Swagger 的 Authorize 中填写。', '', '代码中的请求/响应模型是字段定义的唯一来源；前端只通过这些接口调用业务。', '']
    operations = 0
    for path, methods in spec['paths'].items():
        for method, op in methods.items():
            if method not in ('get', 'post', 'patch', 'put', 'delete'):
                continue
            operations += 1
            lines.extend([f'## {method.upper()} `{path}`', '', f"分组：{', '.join(op.get('tags', []))}；鉴权：{'Bearer access token' if op.get('security') else '无需业务凭证'}。", ''])
            parameters = op.get('parameters', [])
            if parameters:
                lines.extend(['| 参数 | 位置 | 必填 | 约束 |', '|---|---|---|---|'])
                for param in parameters:
                    s = param.get('schema', {})
                    constraints = {k: v for k,v in s.items() if k in ('type', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength', 'default', 'anyOf')}
                    lines.append(f"| {param['name']} | {param['in']} | {'是' if param.get('required') else '否'} | `{json.dumps(constraints,ensure_ascii=False)}` |")
                lines.append('')
            body = op.get('requestBody', {}).get('content', {})
            if 'application/json' in body:
                lines.extend(['请求体示例：', '', '```json', json.dumps(sample(body['application/json']['schema']), ensure_ascii=False, indent=2), '```', ''])
            elif body:
                lines.extend(['请求体：`multipart/form-data`，字段 `file` 为原著文件；文件名不允许带路径。', ''])
            status = next(x for x in op['responses'] if x.startswith('2'))
            schema = op['responses'][status].get('content', {}).get('application/json', {}).get('schema', {})
            success = sample(schema)
            if isinstance(success, dict):
                success.update(code=0, message='成功')
                if path == '/health/live':
                    success['data'] = {'alive': True}
                elif path == '/health/ready':
                    success['data'] = {'ready': True, 'models_checked': False}
                elif path == '/api/auth/logout':
                    success['data'] = {'logged_out': True}
                elif method == 'delete':
                    success['data'] = {'cleared': True} if path.endswith(('/messages', '/model-settings')) else {'deleted': True}
                    if path.endswith('/{file_id}'):
                        success['data'].update(book_id='<书籍ID>', remaining_chunk_count=0)
                if path in ('/api/auth/login', '/api/auth/refresh'):
                    success['data']['expires_in'] = 7200
            lines.extend([f'成功响应示例（HTTP {status}）：', '', '```json', json.dumps(success, ensure_ascii=False, indent=2), '```', ''])
            error_status, code, message = (401, 'AUTH_REQUIRED', '请先登录') if op.get('security') else (422, 'VALIDATION_ERROR', '请求参数无效')
            if path == '/health/live':
                error_status, code, message = 500, 'INTERNAL_ERROR', '服务错误'
            if path == '/health/ready':
                error_status, code, message = 503, 'DEPENDENCY_UNAVAILABLE', '本地嵌入服务尚未就绪'
            error_data = {'errors': [{'field': 'body.username' if path.endswith('/login') else 'body.refresh_token', 'reason': 'missing'}]} if code == 'VALIDATION_ERROR' else None
            lines.extend([f'失败响应示例（HTTP {error_status}）：', '', '```json', json.dumps({'code': code, 'message': message, 'data': error_data, 'request_id': 'example-request-id'}, ensure_ascii=False, indent=2), '```', ''])
    (output / 'P0_FastAPI接口契约定稿.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Exported {operations} operations across {len(spec["paths"])} paths; no runtime database or model calls.')


if __name__ == '__main__':
    export()
