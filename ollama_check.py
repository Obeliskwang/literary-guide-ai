"""Verify required Ollama models exist locally before starting the app or CLI."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from config import EMBED_MODEL, EMBED_TYPE, LLM_MODEL, LLM_TYPE, OLLAMA_EMBED_MODEL

logger = logging.getLogger(__name__)


class OllamaModelsError(RuntimeError):
    """Raised when Ollama is unreachable or a configured model is not installed locally."""


def _api_tags_url() -> str:
    base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    return f"{base}/api/tags"


def _model_is_present(required: str, installed_names: list[str]) -> bool:
    """Match config names like `llama3.2` to Ollama tags like `llama3.2:latest`."""
    for name in installed_names:
        if not name:
            continue
        if name == required or name.startswith(required + ":"):
            return True
    return False


def _fetch_installed_model_names() -> list[str]:
    url = _api_tags_url()
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as e:
        raise OllamaModelsError(
            f"Cannot reach Ollama at {url!r}: {e}\n"
            "Start the Ollama service (e.g. run `ollama serve` or launch the Ollama app), "
            "then try again. To use another host, set OLLAMA_HOST in the environment."
        ) from e
    except json.JSONDecodeError as e:
        raise OllamaModelsError(f"Invalid JSON from Ollama at {url!r}: {e}") from e

    models = payload.get("models") or []
    names: list[str] = []
    for m in models:
        if isinstance(m, dict) and "name" in m:
            names.append(str(m["name"]))
    return names


def ensure_ollama_models(embedding_only=False) -> None:
    """
    Confirm chat and embedding models from config exist in local Ollama.
    (VISION_MODEL 暂时注释掉，项目暂时不需要 llava 模型)

    Set SKIP_OLLAMA_CHECK=1 to disable (e.g. tests, air-gapped CI without Ollama).

    Supports mixed mode: when LLM_TYPE or EMBED_TYPE is "openai", the corresponding
    model check is skipped since it will be accessed via OpenAI API instead of Ollama.
    """
    if os.environ.get("SKIP_OLLAMA_CHECK", "").lower() in ("1", "true", "yes"):
        logger.debug("Skipping Ollama model check (SKIP_OLLAMA_CHECK is set)")
        return

    # 根据模型类型决定需要检查哪些模型
    required = []
    
    if not embedding_only and LLM_TYPE == "ollama":
        required.append(("LLM_MODEL", LLM_MODEL))
    
    if embedding_only:
        required.append(("OLLAMA_EMBED_MODEL", OLLAMA_EMBED_MODEL))
    elif EMBED_TYPE == "ollama":
        required.append(("EMBED_MODEL", EMBED_MODEL))
    
    # ("VISION_MODEL", VISION_MODEL),  # 暂时注释掉，项目暂时不需要 llava 模型

    # 如果没有需要检查的 Ollama 模型，直接返回
    if not required:
        logger.debug("No Ollama models configured (all using OpenAI API), skipping check")
        return

    installed = _fetch_installed_model_names()
    logger.info(
        "Ollama model check: %s tag(s) at %s",
        len(installed),
        _api_tags_url(),
    )

    missing: list[tuple[str, str]] = []
    for cfg_key, model_name in required:
        if not _model_is_present(model_name, installed):
            missing.append((cfg_key, model_name))

    if not missing:
        return

    lines = [
        "Required Ollama models are missing locally. Pull them first, then verify with `ollama list`:",
        "",
    ]
    for cfg_key, model_name in missing:
        lines.append(f"  - {cfg_key}={model_name!r}  →  ollama pull {model_name}")
    lines.extend(
        [
            "",
            f"Config: `config.py`. Ollama API: {_api_tags_url()}",
        ]
    )
    raise OllamaModelsError("\n".join(lines))
