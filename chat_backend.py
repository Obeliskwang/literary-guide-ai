"""Per-request chat configuration, independent of local document embeddings."""
from dataclasses import dataclass, field
from urllib.parse import urlsplit
import json
import logging
import requests

logger = logging.getLogger(__name__)


class ModelHTTPError(RuntimeError):
    """Only locally constructed diagnostics; never expose provider response bodies."""

    def __init__(self, status):
        reasons = {
            400: "请求参数不被模型支持",
            401: "API Key 无效或认证失败",
            402: "账户余额不足",
            403: "账户或模型访问被拒绝",
            404: "接口地址或模型 ID 不存在",
            422: "请求参数格式无效",
            429: "请求频率或额度受限",
            500: "模型服务内部错误",
            503: "模型服务暂时不可用",
        }
        self.safe_message = f"模型请求失败（HTTP {status}）：{reasons.get(status, '服务返回异常状态')}"
        super().__init__(self.safe_message)


class EmptyModelResponseError(RuntimeError):
    def __init__(self, truncated):
        self.safe_message = (
            "模型输出达到 token 上限，未生成正文"
            if truncated else "模型请求成功，但未返回回答正文"
        )
        super().__init__(self.safe_message)


@dataclass(frozen=True)
class ChatSettings:
    mode: str
    model: str
    base_url: str
    api_key: str = field(default="", repr=False)

    def validate(self):
        if self.mode not in ("ollama", "api") or not self.model.strip():
            raise ValueError("请选择回答方式并填写模型 ID")
        url = urlsplit(self.base_url.strip())
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
            raise ValueError("请填写有效的 API 基础网址")
        if self.mode == "api" and not self.api_key.strip():
            raise ValueError("请填写 API Key")


def complete_chat(settings, prompt, temperature):
    settings.validate()
    messages = [{"role": "system", "content": "你是一个专业的文学名著导读助手，请依据提供的原著回答并注明出处。"}, {"role": "user", "content": prompt}]
    base = settings.base_url.strip().rstrip("/")
    if settings.mode == "api":
        payload = {"model": settings.model.strip(), "messages": messages, "temperature": temperature, "max_tokens": 2048, "stream": False}
        if urlsplit(base).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        response = requests.post(base + "/chat/completions", headers={"Authorization": "Bearer " + settings.api_key.strip()}, json=payload, timeout=60)
    else:
        response = requests.post(base + "/api/chat", json={"model": settings.model.strip(), "messages": messages, "options": {"temperature": temperature, "num_predict": 256}, "stream": False}, timeout=60)
    if response.status_code != 200:
        error = ModelHTTPError(response.status_code)
        logger.error("complete_chat: %s", error.safe_message)
        raise error
    logger.info("complete_chat: HTTP %s", response.status_code)
    data = response.json()
    if settings.mode == "api":
        choice = data["choices"][0]
        content = choice["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            truncated = choice.get("finish_reason") == "length"
            logger.error("complete_chat: empty content, truncated=%s, has_reasoning=%s", truncated, bool(choice["message"].get("reasoning_content")))
            raise EmptyModelResponseError(truncated)
        return content
    return data.get("message", {}).get("content", "")


def choose_tool(settings, question, tools):
    """Ask the configured model to select a tool; return None when its API lacks tool support."""
    settings.validate()
    messages = [
        {"role": "system", "content": "你是文学助手的工具路由器。根据用户明确提到的人物关系图、人物表/身份或事件表/事迹选择且只选择一个最匹配的工具；普通文学问答不要调用工具。只提取用户原话中存在的筛选参数。"},
        {"role": "user", "content": question},
    ]
    base = settings.base_url.strip().rstrip("/")
    try:
        if settings.mode == "api":
            payload = {"model": settings.model.strip(), "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0, "max_tokens": 128, "stream": False}
            if urlsplit(base).hostname == "api.deepseek.com":
                payload["thinking"] = {"type": "disabled"}
            response = requests.post(base + "/chat/completions", headers={"Authorization": "Bearer " + settings.api_key.strip()}, json=payload, timeout=20)
            if response.status_code != 200:
                logger.warning("choose_tool: provider does not accept tool routing, status=%s", response.status_code)
                return None
            calls = response.json().get("choices", [{}])[0].get("message", {}).get("tool_calls") or []
        else:
            response = requests.post(base + "/api/chat", json={"model": settings.model.strip(), "messages": messages, "tools": tools, "stream": False, "options": {"temperature": 0, "num_predict": 128}}, timeout=20)
            if response.status_code != 200:
                logger.warning("choose_tool: Ollama model does not accept tool routing, status=%s", response.status_code)
                return None
            calls = response.json().get("message", {}).get("tool_calls") or []
        if not calls:
            return None
        function = calls[0].get("function") or {}
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return {"name": function.get("name"), "arguments": arguments if isinstance(arguments, dict) else {}}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("choose_tool: falling back after %s", type(exc).__name__)
        return None
