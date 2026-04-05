import json
import os
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential
from state.pipeline_state import PipelineState

# Free models on Groq (console.groq.com)
FAST  = "llama-3.1-8b-instant"     # lightweight — use for ProfilerAgent
SMART = "llama-3.3-70b-versatile"  # reasoning  — use for Synthesis, Remediation, Report


class BaseAgent:
    name: str = "base"
    model: str = FAST  # subclasses override this

    def __init__(self, state: PipelineState):
        self.state = state
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=2, min=4, max=30))
    def call_llm(self, system: str, user: str) -> str:
        """Call the LLM and return raw text."""
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return resp.choices[0].message.content

    def call_llm_json(self, system: str, user: str):
        """Call the LLM and parse the response as JSON.
        Strips markdown code fences if present."""
        raw = self.call_llm(system, user).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0]
        return json.loads(raw)

    def run(self) -> None:
        raise NotImplementedError
