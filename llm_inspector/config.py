_config: dict = {}

def configure(**kwargs) -> None:
    """
    Set configuration values for llm_inspector at startup.
    All parameters are optional — only set what you have.
    Calling configure() multiple times merges values 
    (last write wins per key).
    
    Supported keys:
        openai_api_key      str
        anthropic_api_key   str  
        gemini_api_key      str
        google_api_key      str  (alias for gemini_api_key)
        deepseek_api_key    str
        deepseek_base_url   str  (default: "https://api.deepseek.com")
        custom_api_key      str  (for any OpenAI-compatible provider)
        custom_base_url     str  (for Ollama, vLLM, etc.)
    """
    _config.update(kwargs)

def get(key: str, fallback_env_var: str = None):
    """
    Get a config value. Checks _config first, then falls back to 
    os.environ if fallback_env_var is provided.
    Never raises — returns None if not found anywhere.
    """
    if key in _config:
        return _config[key]
    if fallback_env_var:
        import os
        return os.environ.get(fallback_env_var)
    return None

def get_provider_credentials(provider: str) -> dict:
    """
    Returns {"api_key": ..., "base_url": ...} for the given provider,
    checking configure() values first, then env vars as fallback.
    Returns {"api_key": None, "base_url": None} if nothing found.
    """
    if provider == "openai":
        return {
            "api_key": get("openai_api_key", "OPENAI_API_KEY"),
            "base_url": None,
        }
    elif provider == "deepseek":
        return {
            "api_key": get("deepseek_api_key", "DEEPSEEK_API_KEY"),
            "base_url": get("deepseek_base_url") or "https://api.deepseek.com",
        }
    elif provider == "anthropic":
        return {
            "api_key": get("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "base_url": None,
        }
    elif provider == "gemini":
        return {
            "api_key": get("gemini_api_key", "GEMINI_API_KEY") 
                       or get("google_api_key", "GOOGLE_API_KEY"),
            "base_url": None,
        }
    elif provider in ("openai-compatible", "ollama"):
        return {
            "api_key": get("custom_api_key") or "not-needed",
            "base_url": get("custom_base_url"),
        }
    return {"api_key": None, "base_url": None}
