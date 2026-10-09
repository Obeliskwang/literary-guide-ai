"""Streamlit's only business dependency: HTTP, bounded refresh and stable request keys."""
import os
import requests


class APIError(Exception):
    def __init__(self, code, message, status=0, request_id=''):
        super().__init__(message)
        self.code, self.status, self.request_id = code, status, request_id


class APIClient:
    def __init__(self, access_token='', refresh_token='', transport=None):
        self.base_url = os.getenv('LITERARY_API_URL', 'http://127.0.0.1:8000').rstrip('/')
        self.public_url = os.getenv('LITERARY_PUBLIC_API_URL', 'http://localhost:8000').rstrip('/')
        self.access_token, self.refresh_token = access_token, refresh_token
        self.transport = transport or requests.Session()
        if transport is None:
            self.transport.trust_env = False  # Local service must not accidentally route through a system proxy.

    def request(self, method, path, *, json=None, params=None, files=None, key=None, refresh=True):
        headers = {'Authorization': 'Bearer ' + self.access_token} if self.access_token else {}
        if key:
            headers['Idempotency-Key'] = key
        try:
            response = self.transport.request(method, self.base_url + path, headers=headers, json=json, params=params, files=files, timeout=(5, float(os.getenv('LITERARY_API_READ_TIMEOUT', '900'))))
        except requests.Timeout:
            raise APIError('CLIENT_TIMEOUT', '请求等待超时；后端可能仍在处理，请使用原请求重试') from None
        except requests.RequestException:
            raise APIError('API_UNAVAILABLE', '无法连接 API，请确认后端服务已启动') from None
        if response.status_code == 401 and refresh and self.refresh_token and path not in ('/api/auth/login', '/api/auth/refresh', '/api/auth/logout'):
            self.restore()
            if files:
                for value in files.values():
                    if isinstance(value, tuple) and hasattr(value[1], 'seek'):
                        value[1].seek(0)
            return self.request(method, path, json=json, params=params, files=files, key=key, refresh=False)
        try:
            value = response.json()
        except ValueError:
            raise APIError('INVALID_RESPONSE', 'API 返回格式无效', response.status_code) from None
        if response.status_code >= 400 or value.get('code') != 0:
            raise APIError(value.get('code', 'API_ERROR'), value.get('message', '请求失败'), response.status_code, value.get('request_id', ''))
        return value['data']

    def restore(self):
        result = self.request('POST', '/api/auth/refresh', json={'refresh_token': self.refresh_token}, refresh=False)
        self.access_token = result['access_token']
        self.refresh_token = result['refresh_token']

    def binary(self, path, *, refresh=True):
        headers = {'Authorization': 'Bearer ' + self.access_token} if self.access_token else {}
        try:
            response = self.transport.request('GET', self.base_url + path, headers=headers, timeout=(5, float(os.getenv('LITERARY_API_READ_TIMEOUT', '900'))))
        except requests.Timeout:
            raise APIError('CLIENT_TIMEOUT', '请求等待超时') from None
        except requests.RequestException:
            raise APIError('API_UNAVAILABLE', '无法连接 API，请确认后端服务已启动') from None
        if response.status_code == 401 and refresh and self.refresh_token:
            self.restore()
            return self.binary(path, refresh=False)
        if response.status_code >= 400:
            try:
                value = response.json()
            except ValueError:
                raise APIError('API_ERROR', '资源读取失败', response.status_code) from None
            raise APIError(value.get('code', 'API_ERROR'), value.get('message', '资源读取失败'), response.status_code, value.get('request_id', ''))
        return response.content, response.headers.get('content-type', 'application/octet-stream').split(';', 1)[0]

    def all(self, path, **params):
        items, page = [], 1
        while True:
            result = self.request('GET', path, params=dict(params, page=page, page_size=100))
            items.extend(result['items'])
            if len(items) >= result['total'] or not result['items']:
                return items
            page += 1
