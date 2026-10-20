import unittest

from jarvis import config
from jarvis.provider import _normalize_ollama_host, _resolve_model


class OllamaProviderTests(unittest.TestCase):
    def test_normalize_ollama_host_strips_api_suffix(self):
        self.assertEqual(
            _normalize_ollama_host("http://localhost:11434/api"),
            "http://localhost:11434",
        )

    def test_normalize_ollama_host_strips_trailing_slashes(self):
        self.assertEqual(
            _normalize_ollama_host("http://localhost:11434/"),
            "http://localhost:11434",
        )
        self.assertEqual(
            _normalize_ollama_host("http://localhost:11434/api/"),
            "http://localhost:11434",
        )

    def test_normalize_ollama_host_keeps_plain_host(self):
        self.assertEqual(
            _normalize_ollama_host("http://localhost:11434"),
            "http://localhost:11434",
        )

    def test_resolve_model_returns_model_name(self):
        self.assertEqual(_resolve_model("qwen2.5:1.5b"), "qwen2.5:1.5b")

    def test_resolve_model_empty_falls_back_to_config(self):
        # The fallback must match the configured provider's model,
        # not a hardcoded name.
        if config.MODEL_PROVIDER == "ollama":
            self.assertEqual(_resolve_model(""), config.OLLAMA_MODEL or "qwen2.5:0.5b")
        else:
            self.assertTrue(_resolve_model(""))  # non-empty default



if __name__ == "__main__":
    unittest.main()
