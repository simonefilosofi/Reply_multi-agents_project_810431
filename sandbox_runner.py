"""Isolated subprocess runner for LLM-generated fix functions.

Receives all inputs via CLI arguments, runs the generated function in a
separate process with no access to the main pipeline state, and writes
the result to a temporary output CSV.
"""

import sys
import pandas as pd


def main():
    if len(sys.argv) != 5:
        print("Usage: sandbox_runner.py <input_csv> <func_py> <output_csv> <col>",
              file=sys.stderr)
        sys.exit(1)

    input_path  = sys.argv[1]
    func_path   = sys.argv[2]
    output_path = sys.argv[3]
    col         = sys.argv[4]

    df = pd.read_csv(input_path, dtype=str)

    if col not in df.columns:
        print(f"Column '{col}' not found in input CSV. "
              f"Available: {list(df.columns)}", file=sys.stderr)
        sys.exit(1)

    with open(func_path) as f:
        code = f.read()

    import numpy as np
    local_ns = {"pd": pd, "np": np, "df": df, "col": col}
    exec(code, local_ns)  # noqa: S102

    if "fix" not in local_ns:
        print("Generated code must define a function named 'fix'.", file=sys.stderr)
        sys.exit(1)

    fix_func = local_ns["fix"]
    fix_func(df, col)

    df.to_csv(output_path, index=False)


if __name__ == "__main__":
    main()
