"""Loads the versioned system prompt for an LLM-calling agent from prompts/<name>.md. A missing file raises rather than degrading to an empty prompt, so a renamed prompt fails at the call site instead of silently changing what an agent is asked."""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Return the contents of prompts/<name>.md as a system-prompt string."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
