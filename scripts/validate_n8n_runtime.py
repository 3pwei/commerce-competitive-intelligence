#!/usr/bin/env python3
"""CLI wrapper for n8n runtime artifact validation."""

import argparse
from pathlib import Path

from competitive_intelligence.runtime_validation import validate_n8n_runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execution-output", type=Path, required=True)
    args = parser.parse_args()
    validate_n8n_runtime(args.output_dir, args.execution_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
