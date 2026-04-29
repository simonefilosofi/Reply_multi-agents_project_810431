"""Quick connectivity probe for the configured Anthropic + OpenAI models.

Runs a tiny prompt against each tier (smart / fast) and against each provider
(primary / fallback) to confirm the API keys in .env can reach the model
identifiers pinned in ``state_demo.config.Settings``. Used as a manual
sanity check before exercising the full pipeline.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from pydantic_ai import Agent  # noqa: E402

from state_demo import settings  # noqa: E402


def probe(label: str, model_id: str) -> tuple[bool, str]:
    t0 = time.monotonic()
    try:
        agent = Agent(model=model_id, output_type=str, instructions="Reply with one short word.")
        result = agent.run_sync("Say PONG.", model_settings={"max_tokens": 16})
        elapsed = time.monotonic() - t0
        return True, f"{label} [{model_id}] ok in {elapsed:.2f}s -> {result.output!r}"
    except Exception as exc:
        elapsed = time.monotonic() - t0
        msg = f"{label} [{model_id}] FAIL in {elapsed:.2f}s -> {type(exc).__name__}: {exc}"
        return False, msg


def main() -> int:
    targets = [
        ("smart-primary", settings.models.smart_model),
        ("smart-fallback", settings.models.fallback_smart_model),
        ("fast-primary", settings.models.fast_model),
        ("fast-fallback", settings.models.fallback_fast_model),
    ]
    print("Anthropic key set:", bool(settings.anthropic_api_key))
    print("OpenAI key set:   ", bool(settings.openai_api_key))
    failures = 0
    for label, model_id in targets:
        ok, msg = probe(label, model_id)
        print(msg)
        if not ok:
            traceback.print_exc(limit=1)
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
