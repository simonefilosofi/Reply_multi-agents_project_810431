"""Base agent class providing the Think-Act-Observe-Reply protocol,
LLM integration via OpenAI, and structured logging for all pipeline agents."""

import json
import os
from datetime import datetime

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from state_demo.pipeline_state import PipelineState

FAST = "gpt-4o-mini"
SMART = "gpt-4o-mini"


class BaseAgent:
    name: str = "base"
    model: str = FAST
    INSTRUCTION: str = ""  # subclasses define their role and personality

    def __init__(self, state: PipelineState):
        self.state = state
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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

    def call_llm_json(self, user: str, max_tokens: int = 4096,
                      required_keys: list = None):
        """Call the LLM, parse the response as JSON, and optionally validate keys."""
        raw = self.call_llm(user, max_tokens).strip()
        start = min(
            (raw.find(c) for c in "{[" if raw.find(c) != -1), default=0,
        )
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        result = json.loads(raw[start:end])
        if required_keys:
            missing = [k for k in required_keys if k not in result]
            if missing:
                raise ValueError(
                    f"LLM JSON response missing required keys: {missing}. "
                    f"Got keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}"
                )
        return result

    def llm_enrich_issues(
        self,
        issues: list,
        df,
        allowed_types: set,
    ) -> list:
        """Enrich deterministic issue findings with LLM analysis.

        The LLM receives the deterministic findings (as confirmed anchors) and
        column samples, then returns an enriched list with:
        - richer, example-based detail fields for existing findings
        - any additional issues clearly visible in the samples

        All original issues are always preserved in the output regardless of
        what the LLM returns. Falls back to original issues on any error.
        """
        from state_demo.helpers import non_empty_values

        if not issues:
            return issues

        # Samples: columns already flagged + up to 5 unflagged columns
        flagged_cols = {i.get("column", "") for i in issues if i.get("column")}
        unflagged = [c for c in df.columns if c not in flagged_cols][:5]
        sample_cols = list(flagged_cols) + unflagged

        col_samples = {}
        for col in sample_cols:
            if col not in df.columns:
                continue
            nev = non_empty_values(df[col])
            sample = list(nev.sample(min(20, len(nev)), random_state=42).astype(str))
            col_samples[col] = {"dtype": str(df[col].dtype), "sample": sample}

        findings_text = "\n".join(
            f"- [{i['severity'].upper()}] type={i['type']} | "
            f"column='{i.get('column', '')}' | {i['detail']}"
            for i in issues
        )
        from state_demo.constants import ISSUE_TYPES
        types_text = "\n".join(
            f"  {t}: {ISSUE_TYPES.get(t, '')}"
            for t in sorted(allowed_types)
        )
        samples_text = "\n".join(
            f"  '{col}' (dtype={info['dtype']}): {info['sample']}"
            for col, info in col_samples.items()
        )

        user = (
            f"Dataset domain: {self.state.dataset_fingerprint.get('domain', 'unknown')}\n\n"
            f"Column samples:\n{samples_text}\n\n"
            f"Confirmed deterministic findings (you MUST include all of these):\n"
            f"{findings_text}\n\n"
            f"Allowed issue types for this agent:\n{types_text}\n\n"
            "Instructions:\n"
            "1. Return ALL confirmed findings above, enriching 'detail' with specific "
            "example values from the samples (e.g. \"602 non-numeric values such as "
            "'6 unità', '2,0', 'N.D.' — should be integers\").\n"
            "2. Add NEW issues you clearly see in the samples that are not already covered.\n"
            "3. Use ONLY the allowed types listed above.\n"
            "4. 'severity' must be exactly 'high', 'medium', or 'low'.\n"
            "5. 'detail' must be specific: include example values, counts, and expected format.\n"
            'Return JSON: {"issues": [{"type": "...", "column": "...", '
            '"detail": "...", "severity": "..."}]}'
        )

        try:
            result = self.call_llm_json(user, max_tokens=2048,
                                        required_keys=["issues"])
            enriched = result.get("issues", [])

            valid_enriched = [
                i for i in enriched
                if i.get("type") in allowed_types
                and i.get("column", "") in df.columns
                and i.get("severity") in ("high", "medium", "low")
                and i.get("detail", "").strip()
            ]

            # Always preserve original issues — LLM cannot remove them
            enriched_keys = {
                (i["type"], i.get("column", "")) for i in valid_enriched
            }
            merged = list(valid_enriched)
            for issue in issues:
                key = (issue["type"], issue.get("column", ""))
                if key not in enriched_keys:
                    merged.append(issue)

            new_count = len(merged) - len(issues)
            self.log("act",
                     f"LLM enrichment: {len(issues)} deterministic → "
                     f"{len(merged)} issues ({new_count:+d} new)")
            return merged

        except Exception as e:
            self.log("error", f"LLM enrichment failed, keeping deterministic issues: {e}")
            return issues

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
