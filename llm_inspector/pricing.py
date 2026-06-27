"""
pricing.py — Cost tracking dictionary for llm_inspector.

Costs are defined per 1,000 tokens for prompt and completion.
NOTE: These are approximate placeholder values and should be verified 
against each provider's current real pricing page before relying on them 
for actual budgeting.
"""

PRICING = {
    # OpenAI
    "gpt-4o": {"prompt": 0.005, "completion": 0.015},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    
    # Anthropic
    "claude-3-5-sonnet-20241022": {"prompt": 0.003, "completion": 0.015},
    "claude-3-haiku-20240307": {"prompt": 0.00025, "completion": 0.00125},
    
    # Google (Gemini)
    "gemini-1.5-pro": {"prompt": 0.0035, "completion": 0.0105},
    "gemini-1.5-flash": {"prompt": 0.000075, "completion": 0.0003},
    
    # DeepSeek
    "deepseek-chat": {"prompt": 0.00014, "completion": 0.00028},
}
