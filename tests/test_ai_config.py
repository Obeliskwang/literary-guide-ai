"""Verify generic API settings without credentials or network calls."""
import ast
from pathlib import Path
import unittest
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def isolated_function(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class AIConfigTests(unittest.TestCase):
    def test_health_request_uses_custom_credentials_and_url(self):
        requests = MagicMock()
        requests.post.return_value.status_code = 200
        for mode in ("api", "openai"):
            namespace = dict(LLM_TYPE=mode, AI_BASE_URL="https://example.test/v1/", AI_API_KEY="test-only", LLM_MODEL="custom-model", requests=requests, logger=MagicMock())
            check = isolated_function("agent.py", "check_model_health", namespace)
            self.assertTrue(check())
            args, kwargs = requests.post.call_args
            self.assertEqual(args[0], "https://example.test/v1/chat/completions")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-only")
            self.assertEqual(kwargs["json"]["model"], "custom-model")

    def test_sdk_uses_same_settings(self):
        client = MagicMock()
        environment = MagicMock()
        environment.environ.get.side_effect = lambda key, default: default
        namespace = dict(LLM_TYPE="api", AI_BASE_URL="https://example.test", AI_API_KEY="test-only", LLM_MODEL="custom-model", TEMPERATURE=0.5, os=environment, ChatOpenAI=client)
        get_llm = isolated_function("llm.py", "get_llm", namespace)
        get_llm()
        client.assert_called_once_with(model="custom-model", temperature=0.5, api_key="test-only", base_url="https://example.test")

    def test_config_model_selection(self):
        tree = ast.parse((ROOT / "config.py").read_text(encoding="utf-8"))
        statement = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "LLM_MODEL" for target in node.targets))
        for mode, expected in (("api", "custom-model"), ("openai", "custom-model"), ("ollama", "local-model")):
            namespace = dict(LLM_TYPE=mode, AI_MODEL_NAME="custom-model", OLLAMA_LLM_MODEL="local-model")
            exec(compile(ast.Module(body=[statement], type_ignores=[]), "config.py", "exec"), namespace)
            self.assertEqual(namespace["LLM_MODEL"], expected)
