from unittest.mock import MagicMock
from llm_inspector.patches.openai_patch import _detect_provider

def test_detect_provider():
    def make_mock_client(base_url):
        client = MagicMock()
        client._client = MagicMock()
        client._client.base_url = base_url
        return client

    cases = [
        ("https://api.groq.com/openai/v1", "groq"),
        ("https://api.mistral.ai/v1", "mistral"),
        ("https://api.perplexity.ai", "perplexity"),
        ("https://api.together.xyz/v1", "together"),
        ("https://openrouter.ai/api/v1", "openrouter"),
        ("https://api.deepseek.com", "deepseek"),
        ("https://api.openai.com/v1", "openai"),
        ("", "openai"),
        (None, "openai"),
        ("http://localhost:11434/v1", "ollama"),
        ("https://myinstance.openai.azure.com", "azure_openai"),
    ]

    for base_url, expected in cases:
        client = make_mock_client(base_url)
        res = _detect_provider(client)
        assert res == expected, f"Expected {expected} for base_url {base_url!r}, got {res!r}"
        print(f"base_url={base_url!r} -> {res!r} (OK)")

if __name__ == "__main__":
    test_detect_provider()
    print("All provider detection tests passed.")
