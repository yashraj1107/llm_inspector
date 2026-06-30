"""
llm_inspector — storage, async queue pipeline, and SDK patches.

Quickstart (patches every supported SDK and starts the background worker):

    import llm_inspector
    llm_inspector.auto()

Providers patched (silently skipped if the SDK is not installed):
  - OpenAI   (openai.resources.chat.completions.Completions.create)
  - Anthropic (anthropic.resources.messages.Messages.create)
  - Gemini   (google.genai.models.Models.generate_content)

Or use individual symbols:

    from llm_inspector import start_worker, enqueue_event
    from llm_inspector.patches import patch_openai, patch_anthropic, patch_gemini
"""

from llm_inspector.queue_worker import enqueue_event, start_worker
from llm_inspector.patches import (
    apply_all_patches,
    patch_anthropic,
    patch_gemini,
    patch_openai,
)
from llm_inspector.storage import db_path
from llm_inspector.spans import span


def auto() -> None:
    """
    Convenience entry-point: start the background worker and install all
    registered SDK patches in one call.

    Idempotent — safe to call multiple times; subsequent calls are no-ops.
    SDKs that are not installed are silently skipped.
    """
    start_worker()
    apply_all_patches()


__all__ = [
    "auto",
    "enqueue_event",
    "start_worker",
    "apply_all_patches",
    "patch_openai",
    "patch_anthropic",
    "patch_gemini",
    "db_path",
    "span",
]
__version__ = "0.3.2"
