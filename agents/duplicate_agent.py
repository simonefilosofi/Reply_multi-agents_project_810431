"""Layer 1 duplicate detection agent. Identifies fully duplicate rows,
duplicate column pairs flagged by the profiler, and key-collision rows
that share key column values but differ in other columns. Emits typed Issue
instances into state.duplicate_report after Step 9.
"""

from agents_demo._enrichment import enrich_with_llm
from agents_demo.base_agent import SMART, BaseAgent
from state.constants import DUPLICATE_ISSUE_TYPES
from state.issues import AgentReport, parse_issues
from tools import detect_duplicate_columns, detect_duplicate_rows, detect_key_collisions


class DuplicateAgent(BaseAgent):
    name = "duplicate"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a duplicate detection specialist. You identify fully duplicate "
        "rows, redundant column pairs, and key-collision records (rows that share "
        "key values but differ in other columns). You summarize duplicate issues "
        "in 2-3 sentences, noting the scale and likely cause. "
        "IMPORTANT: a column of numeric codes (e.g. cod_imposta, cod_tipoimposta) "
        "and its corresponding text description column (e.g. imposta, tipo_imposta) "
        "are NOT duplicates — they carry complementary information and both must be "
        "preserved. Only flag columns as duplicates when they contain truly identical "
        "or near-identical values."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint

        raw: list[dict] = []
        raw += detect_duplicate_rows(df)
        raw += detect_duplicate_columns(df, fp.get("likely_duplicate_pairs", []))

        # Check id_columns first — violations there are primary key errors.
        # Then check suggested_key_columns for business-key collisions.
        # Use dict.fromkeys to deduplicate while preserving order.
        key_cols = list(
            dict.fromkeys(
                [c for c in fp.get("id_columns", []) if c in df.columns]
                + [c for c in (fp.get("suggested_key_columns") or []) if c in df.columns]
            )
        )
        collision_issues, skip_reason = detect_key_collisions(df, key_cols)
        if skip_reason:
            self.log("act", skip_reason)
        id_col_set = set(fp.get("id_columns", []))
        for issue in collision_issues:
            issue_cols = {c.strip() for c in issue["column"].split(",")}
            if issue_cols & id_col_set:
                issue["severity"] = "high"
                issue["detail"] = "PRIMARY KEY VIOLATION: " + issue["detail"]
        raw += collision_issues

        issues = parse_issues(raw, source=self.name, allowed_types=DUPLICATE_ISSUE_TYPES)
        issues = enrich_with_llm(self, issues, df, DUPLICATE_ISSUE_TYPES)
        report: AgentReport = {"issues": issues, "total_issues": len(issues)}
        self.state.duplicate_report = report

    def observe(self):
        issues = self.state.duplicate_report["issues"]
        row_dups = sum(1 for i in issues if i.type == "duplicate_rows")
        col_dups = sum(1 for i in issues if i.type == "duplicate_columns")
        key_dups = sum(1 for i in issues if i.type == "duplicate_key")
        self.log(
            "observe",
            f"Found {len(issues)} duplicate issues: "
            f"{row_dups} row, {col_dups} column, {key_dups} key-collision",
        )

    def reply(self):
        self.summarize_issues(
            self.state.duplicate_report["issues"],
            "duplicate_summary",
            "duplicate",
        )
