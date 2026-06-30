"""
This file generates SYNTHETIC test data only. Every row it produces is tagged 'demo'.
Never treat output from this file as real captured trace data.
"""

import json
import random
import time
import uuid

PROVIDERS = ["openai", "anthropic", "google", "cohere", "mistral"]
MODELS = {
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    "google":    ["gemini-1.5-pro", "gemini-1.5-flash"],
    "cohere":    ["command-r-plus", "command-r"],
    "mistral":   ["mistral-large-latest", "mistral-small-latest"],
}

FAKE_USERS = [f"user_{i:04d}" for i in range(1, 11)]

ERROR_MESSAGES = [
    "RateLimitError: Too many requests",
    "TimeoutError: upstream timed out after 30 s",
    "AuthenticationError: invalid API key",
    "ServiceUnavailableError: the model is overloaded",
]

def _make_fake_event(index: int) -> dict:
    provider = random.choice(PROVIDERS)
    model    = random.choice(MODELS[provider])
    status   = "ok" if index % 2 == 0 else "error"

    event: dict = {
        "id":        str(uuid.uuid4()),
        "timestamp": int(time.time()),
        "provider":  provider,
        "model":     model,
        "request_json": json.dumps({
            "messages": [{"role": "user", "content": f"Test prompt #{index}"}],
            "temperature": round(random.uniform(0.0, 1.0), 2),
        }),
        "latency_ms":        random.randint(50, 3000),
        "prompt_tokens":     random.randint(10, 500),
        "completion_tokens": random.randint(5, 300) if status == "ok" else None,
        "status":            status,
        "user_id":           random.choice(FAKE_USERS),
        "tags":              "demo",
    }

    if status == "ok":
        event["response_json"] = json.dumps({
            "choices": [{"message": {"content": f"Fake response for prompt #{index}"}}],
        })
        event["error_message"] = None
    else:
        event["response_json"] = None
        event["error_message"] = random.choice(ERROR_MESSAGES)

    return event

def generate_demo_events(count: int) -> list[dict]:
    return [_make_fake_event(i) for i in range(count)]
