"""Cross-platform encryption for login-scoped model credentials."""
import base64
import ctypes
import hashlib
import os
from pathlib import Path
from ctypes import wintypes

from cryptography.fernet import Fernet, InvalidToken


PREFIX = b"fernet:v1:"


class Blob(ctypes.Structure):
    _fields_ = (("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte)))


def _dpapi_transform(value, encrypt):
    """Read legacy Windows DPAPI values created before container support."""
    if os.name != "nt":
        raise ValueError("无法在当前平台读取旧版 Windows DPAPI 密文")
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("本地密钥加密或解密失败")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def _environment_key():
    value = os.getenv("LITERARY_SETTINGS_KEY", "")
    if not value:
        return None
    if len(value.encode()) < 32:
        raise ValueError("LITERARY_SETTINGS_KEY 至少需要 32 字节")
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())


def _file_key(path):
    path = Path(path)
    try:
        key = path.read_bytes().strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        candidate = Fernet.generate_key()
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = path.read_bytes().strip()
        else:
            with os.fdopen(descriptor, "wb") as target:
                target.write(candidate)
            key = candidate
    try:
        Fernet(key)
    except (TypeError, ValueError) as exc:
        raise ValueError("模型配置加密密钥无效") from exc
    return key


def _fernet(key_path):
    key = _environment_key() or _file_key(key_path)
    return Fernet(key)


def protect(value, key_path):
    if not isinstance(value, bytes):
        raise TypeError("待加密内容必须为 bytes")
    return PREFIX + _fernet(key_path).encrypt(value)


def unprotect(value, key_path):
    if value.startswith(PREFIX):
        try:
            return _fernet(key_path).decrypt(value[len(PREFIX):])
        except InvalidToken as exc:
            raise ValueError("模型配置密文无法解密") from exc
    return _dpapi_transform(value, False)
