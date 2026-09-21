"""Command-line entry point for the demo project."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    return argparse.ArgumentParser(
        prog="competitive-intelligence",
        description="Competitive pricing and review analysis demo.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the placeholder CLI."""
    build_parser().parse_args(argv)
    return 0
