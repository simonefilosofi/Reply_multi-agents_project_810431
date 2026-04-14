"""Base agent class providing the Think-Act-Observe-Reply protocol,
LLM integration via Groq, and structured logging for all pipeline agents."""

import json
import os
from datetime import datetime

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from state_demo.pipeline_state import PipelineState

FAST = "llama-3.1-8b-instant"
SMART = "llama-3.3-70b-versatile"


class BaseAgent:
    name: str = "base"
    model: str = FAST
    INSTRUCTION: str = ""  # subclasses define their role and personality

    def __init__(self, state: PipelineState):
        self.state = state
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.prompt: str = ""

    def run(self, prompt: str = "") -> None:
        """Execute the full Think-Act-Observe-Reply cycle for the given task prompt."""
        self.prompt = prompt
        self.think()
        self.act()
        self.observe()
        self.reply()

    def think(self):
        pass

    def act(self):
        raise NotImplementedError

    def observe(self):
        pass

    def reply(self):
        pass

    def log(self, phase: str, message: str):
        self.state.agent_log.append({
            "agent": self.name,
            "phase": phase,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        })

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=2, min=4, max=30))
    def call_llm(self, user: str, max_tokens: int = 4096) -> str:
        """Call the LLM using INSTRUCTION as the system prompt."""
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": self.INSTRUCTION},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def call_llm_json(self, user: str, max_tokens: int = 4096):
        """Call the LLM and parse the response as JSON."""
        raw = self.call_llm(user, max_tokens).strip()
        start = min(
            (raw.find(c) for c in "{[" if raw.find(c) != -1), default=0,
        )
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        return json.loads(raw[start:end])

    def summarize_issues(self, issues: list, summary_attr: str, noun: str):
        """Ask the LLM to produce a 2-3 sentence summary of the given issues."""
        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}"
            for i in issues
        ) or f"No {noun} issues found."
        try:
            summary = self.call_llm(
                f"Task: {self.prompt}\n\n"
                f"Summarize these {noun} issues in 2-3 sentences:\n\n{issues_text}"
            ).strip()
        except Exception as e:
            self.log("error", str(e))
            summary = f"{len(issues)} {noun} issues found."
        setattr(self.state, summary_attr, summary)
        self.log("reply", summary)
