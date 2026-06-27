"""
registry.py — Central registry for llm_inspector SDK patchers.

Each provider patch module registers itself by calling register_patcher()
at module import time (triggered from patches/__init__.py).

apply_all_patches() iterates every registered patcher and calls it,
isolating failures per provider so one broken patcher never prevents others.
"""

import sys
from typing import Callable

# ---------------------------------------------------------------------------
# Registry store
# ---------------------------------------------------------------------------

# Ordered list of (name, patch_fn) so patchers are applied in registration order.
_registry: list[tuple[str, Callable[[], None]]] = []


def register_patcher(name: str, patch_fn: Callable[[], None]) -> None:
    """Register *patch_fn* under *name*.  Called once per provider at import time."""
    _registry.append((name, patch_fn))


def apply_all_patches() -> None:
    """
    Call every registered patcher in registration order.

    Each patcher is wrapped in its own try/except:
    - A patcher that raises unexpectedly (beyond a simple ImportError it
      handles internally) logs a warning to stderr and the loop continues.
    - One broken provider never prevents the others from being patched.
    """
    for name, patch_fn in _registry:
        try:
            patch_fn()
        except Exception as exc:  # noqa: BLE001
            print(
                f"[llm_inspector] WARNING: failed to apply patch for '{name}': {exc}",
                file=sys.stderr,
            )
