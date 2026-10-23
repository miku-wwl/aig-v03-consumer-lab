"""Command line interface for the AuditGate Lab consumer."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .demo import run_demo


def main() -> int:
    parser = argparse.ArgumentParser(prog="aig_consumer_lab")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run the local approval-gated audit demonstration")
    demo.add_argument(
        "--directory",
        type=Path,
        help="existing private directory or an empty directory to provision",
    )
    demo.add_argument("--entry", default="Deployment candidate build-42 passed review")
    demo.add_argument(
        "--synthetic-test-consent",
        action="store_true",
        help="use clearly labeled synthetic approval and authorization for CI only",
    )
    arguments = parser.parse_args()
    if arguments.command == "demo":
        return asyncio.run(
            run_demo(
                directory=arguments.directory,
                entry=arguments.entry,
                synthetic_test_consent=arguments.synthetic_test_consent,
            )
        )
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
