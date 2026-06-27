"""
llm_inspector.patches — vendor-specific SDK monkey-patches.

Importing this package registers ALL providers automatically via each
module's top-level register_patcher() call.  Callers should use
apply_all_patches() (via llm_inspector.auto()) rather than calling
individual patch functions directly.

Individual patch functions are still exported for explicit use if needed.
"""

# Import order here controls registration order in the registry.
from llm_inspector.patches.registry import apply_all_patches, register_patcher  # noqa: F401
from llm_inspector.patches.openai_patch import patch_openai  # noqa: F401  — also registers
from llm_inspector.patches.anthropic_patch import patch_anthropic  # noqa: F401  — also registers
from llm_inspector.patches.gemini_patch import patch_gemini  # noqa: F401  — also registers

__all__ = [
    "apply_all_patches",
    "register_patcher",
    "patch_openai",
    "patch_anthropic",
    "patch_gemini",
]
