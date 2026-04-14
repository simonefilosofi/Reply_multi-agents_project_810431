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

    def __init__(self, state: PipelineState):
        self.state = state
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def run(self) -> None:
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
    def call_llm(self, system: str, user: str, max_tokens: int = 4096) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    def summarize_issues(self, issues: list, summary_attr: str, noun: str):
        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}"
            for i in issues
        ) or f"No {noun} issues found."
        try:
            summary = self.call_llm(
                f"You are a data quality analyst. Summarize these "
                f"{noun} issues in 2-3 sentences.",
                f"{noun.capitalize()} issues:\n{issues_text}",
            ).strip()
        except Exception as e:
            self.log("error", str(e))
            summary = f"{len(issues)} {noun} issues found."
        setattr(self.state, summary_attr, summary)
        self.log("reply", summary)

    def call_llm_json(self, system: str, user: str, max_tokens: int = 4096):
        raw = self.call_llm(system, user, max_tokens=max_tokens).strip()
        start = min(
            (raw.find(c) for c in "{[" if raw.find(c) != -1), default=0,
        )
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        return json.loads(raw[start:end])
