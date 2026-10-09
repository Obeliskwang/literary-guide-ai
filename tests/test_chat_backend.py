import unittest
from unittest.mock import MagicMock, patch
from chat_backend import ChatSettings, choose_tool, complete_chat
from test_ai_config import isolated_function


class ChatBackendTests(unittest.TestCase):
    @patch("chat_backend.requests.post")
    def test_model_can_select_relationship_graph_tool(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "choices": [{"message": {"tool_calls": [{"function": {
                "name": "show_relationship_graph",
                "arguments": '{"character_name":"孙悟空"}',
            }}]}}]
        }
        tool = {"type": "function", "function": {"name": "show_relationship_graph", "parameters": {"type": "object"}}}
        result = choose_tool(ChatSettings("api", "model", "https://example.test/v1", "key"), "给我孙悟空关系图", [tool])
        self.assertEqual(result, {"name": "show_relationship_graph", "arguments": {"character_name": "孙悟空"}})
        self.assertEqual(post.call_args.kwargs["json"]["tool_choice"], "auto")

    @patch("chat_backend.requests.post")
    def test_tool_selection_falls_back_when_provider_rejects_tools(self, post):
        post.return_value.status_code = 400
        tool = {"type": "function", "function": {"name": "show_relationship_graph", "parameters": {"type": "object"}}}
        self.assertIsNone(choose_tool(ChatSettings("api", "model", "https://example.test", "key"), "人物关系图", [tool]))

    @patch("chat_backend.requests.post")
    def test_remote_credentials_are_request_scoped(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"choices": [{"message": {"content": "answer"}}]}
        for key, model in [("key-a", "model-a"), ("key-b", "model-b")]:
            settings = ChatSettings("api", model, "https://example.test/v1/", key)
            self.assertNotIn(key, repr(settings))
            self.assertEqual(complete_chat(settings, "prompt", 0.5), "answer")
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://example.test/v1/chat/completions")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer " + key)
            self.assertEqual(kwargs["json"]["model"], model)
        self.assertEqual(post.call_count, 2)  # No extra paid health-check call.

    @patch("chat_backend.requests.post")
    def test_local_request_has_no_remote_key(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"message": {"content": "local answer"}}
        self.assertEqual(complete_chat(ChatSettings("ollama", "local-model", "http://localhost:11434"), "prompt", 0.5), "local answer")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://localhost:11434/api/chat")
        self.assertNotIn("headers", kwargs)

    @patch("chat_backend.requests.post")
    def test_deepseek_disables_thinking_and_increases_budget(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"choices": [{"message": {"content": "answer"}}]}
        complete_chat(ChatSettings("api", "deepseek-flash", "https://api.deepseek.com", "key"), "prompt", 0.5)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 2048)
        complete_chat(ChatSettings("api", "m", "https://example.test", "key"), "prompt", 0.5)
        self.assertNotIn("thinking", post.call_args.kwargs["json"])

    @patch("chat_backend.requests.post")
    def test_empty_response_reports_truncation_without_reasoning_text(self, post):
        post.return_value.status_code = 200
        for content, reason in [("", "length"), (None, "stop"), ("   ", "stop")]:
            post.return_value.json.return_value = {"choices": [{"finish_reason": reason, "message": {"content": content, "reasoning_content": "private-reasoning"}}]}
            with self.assertLogs("chat_backend", level="ERROR") as logs:
                with self.assertRaises(RuntimeError) as ctx:
                    complete_chat(ChatSettings("api", "m", "https://example.test", "key"), "prompt", 0.5)
            self.assertNotIn("private-reasoning", " ".join(logs.output))
            self.assertEqual("token 上限" in ctx.exception.safe_message, reason == "length")

    @patch("chat_backend.requests.post")
    def test_invalid_settings_do_not_send_request(self, post):
        for settings in [ChatSettings("api", "m", "https://example.test"), ChatSettings("api", "", "https://example.test", "key"), ChatSettings("api", "m", "invalid", "key")]:
            with self.assertRaises(ValueError):
                complete_chat(settings, "prompt", 0.5)
        post.assert_not_called()

    @patch("chat_backend.requests.post")
    def test_provider_error_body_is_not_exposed(self, post):
        post.return_value.status_code = 401
        post.return_value.text = "echoed-secret-key"
        with self.assertRaises(RuntimeError) as ctx:
            complete_chat(ChatSettings("api", "m", "https://example.test", "key"), "prompt", 0.5)
        self.assertNotIn("echoed-secret-key", str(ctx.exception))

    @patch("chat_backend.requests.post")
    def test_http_diagnostics_do_not_log_credentials_or_body(self, post):
        post.return_value.status_code = 402
        post.return_value.text = "provider-secret-body"
        settings = ChatSettings("api", "m", "https://example.test", "private-api-key")
        with self.assertLogs("chat_backend", level="ERROR") as logs:
            with self.assertRaises(RuntimeError) as ctx:
                complete_chat(settings, "private-question", 0.5)
        output = " ".join(logs.output)
        self.assertIn("HTTP 402", output)
        self.assertIn("账户余额不足", str(ctx.exception))
        for secret in ("provider-secret-body", "private-api-key", "private-question"):
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, ctx.exception.safe_message)

    def test_embeddings_always_local(self):
        factory = MagicMock()
        environment = MagicMock()
        environment.environ.get.side_effect = lambda key, default: default
        get_embeddings = isolated_function("llm.py", "get_embeddings", dict(OllamaEmbeddings=factory, OLLAMA_EMBED_MODEL="bge-m3", os=environment))
        get_embeddings()
        factory.assert_called_once_with(model_name="bge-m3", base_url="http://localhost:11434")

    def test_answer_uses_runtime_settings(self):
        settings = ChatSettings("api", "user-model", "https://example.test", "user-key")
        complete = MagicMock(return_value="answer")
        result = {"results": [], "min_distance": 0.2}
        generate = isolated_function("agent.py", "generate_answer", dict(complete_chat=complete, logger=MagicMock(), build_rag_prompt=MagicMock(return_value="prompt"), TEMPERATURE=0.5, _strip_think_tags=lambda value: value))
        answer = generate(None, "question", retrieved_results=result, chat_settings=settings)
        self.assertEqual(answer["answer"], "answer")
        complete.assert_called_once_with(settings, "prompt", 0.5)

    def test_rejected_retrieval_never_calls_model(self):
        complete = MagicMock()
        generate = isolated_function("agent.py", "generate_answer", dict(complete_chat=complete, REJECTION_MESSAGE="没有原文依据"))
        result = generate(None, "question", retrieved_results={"reject": True})
        self.assertTrue(result["rejected"])
        complete.assert_not_called()

    def test_api_failure_returns_error_without_key(self):
        complete = MagicMock(side_effect=RuntimeError("echoed-secret"))
        generate = isolated_function("agent.py", "generate_answer", dict(complete_chat=complete, logger=MagicMock(), build_rag_prompt=MagicMock(return_value="prompt"), TEMPERATURE=0.5))
        result = generate(None, "question", retrieved_results={"results": []}, chat_settings=ChatSettings("api", "model", "https://example.test", "key"))
        self.assertEqual(result["error"], "RuntimeError")
        self.assertNotIn("echoed-secret", str(result))
