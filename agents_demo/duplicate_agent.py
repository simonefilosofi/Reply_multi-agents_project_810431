"""Layer 1 duplicate detection agent. Identifies fully duplicate rows,
duplicate column pairs flagged by the profiler, and key-collision rows
that share key column values but differ in other columns."""

from agents.base_agent import BaseAgent, SMART


class DuplicateAgent(BaseAgent):
    name = "duplicate"
    model = SMART

    def think(self):
        self.log("think",
                 "Checking for duplicate rows, duplicate column pairs, "
                 "and key-collision records")

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        dup_rows = int(df.duplicated().sum())
        if dup_rows > 0:
            issues.append({
                "column": "_rows_",
                "type": "duplicate_rows",
                "detail": (f"{dup_rows} fully duplicate rows "
                           f"({dup_rows / len(df):.1%} of dataset)"),
                "severity": (
                    "high" if dup_rows / len(df) > 0.05 else "medium"
                ),
            })

        for pair in fp.get("likely_duplicate_pairs", []):
            if (len(pair) == 2
                    and pair[0] in df.columns
                    and pair[1] in df.columns):
                issues.append({
                    "column": f"{pair[0]} / {pair[1]}",
                    "type": "duplicate_columns",
                    "detail": (f"Columns '{pair[0]}' and '{pair[1]}' appear "
                               f"to contain the same data"),
                    "severity": "medium",
                })

        key_cols = [
            c for c in fp.get("suggested_key_columns", []) or []
            if c in df.columns
        ]

        if not key_cols:
            self.log("act",
                     "No valid key columns identified "
                     "-- skipping key-collision check")
        else:
            collisions = df.duplicated(subset=key_cols, keep=False)
            full_dups = df.duplicated(keep=False)
            key_only = collisions & ~full_dups
            n_key_only = int(key_only.sum())

            if n_key_only > 0:
                col_list = ", ".join(key_cols)
                issues.append({
                    "column": col_list,
                    "type": "duplicate_key",
                    "detail": (
                        f"{n_key_only} rows share the same key values "
                        f"in [{col_list}] but differ in other columns "
                        f"-- possible duplicate records or data entry "
                        f"errors"),
                    "severity": "high",
                })

        self.state.duplicate_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def observe(self):
        report = self.state.duplicate_report
        issues = report["issues"]
        row_dups = sum(1 for i in issues if i["type"] == "duplicate_rows")
        col_dups = sum(1 for i in issues if i["type"] == "duplicate_columns")
        key_dups = sum(1 for i in issues if i["type"] == "duplicate_key")
        self.log("observe",
                 f"Found {report['total_issues']} duplicate issues: "
                 f"{row_dups} row, {col_dups} column, {key_dups} key-collision")

    def reply(self):
        self.summarize_issues(
            self.state.duplicate_report["issues"],
            "duplicate_summary", "duplicate",
        )
