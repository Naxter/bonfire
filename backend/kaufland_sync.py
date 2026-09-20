"""Authenticate with and download Kaufland digital receipts.

Usage (from the ``backend/`` directory)::

    python kaufland_sync.py login
    python kaufland_sync.py sync

The login flow is interactive because Kaufland owns the account credentials;
only the resulting refresh token is stored locally below ``data/kaufland/``.
"""

from __future__ import annotations

import argparse
import json

import app.config  # noqa: F401  (loads the repository .env)
from app.kaufland import KauflandConfig, download_kaufland_receipts, login


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download Kaufland digital receipts into Bonfire")
    subparsers = parser.add_subparsers(dest="command", required=True)
    login_parser = subparsers.add_parser("login", help="complete the Kaufland browser login")
    login_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="print the authorization URL without opening a browser",
    )
    subparsers.add_parser("sync", help="download and import all available receipt pages")
    subparsers.add_parser("status", help="show non-secret configuration status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = KauflandConfig.from_environment()
    if args.command == "login":
        result = login(config, no_browser=args.no_browser)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps({"data_dir": str(config.data_dir), "token_file": str(config.token_path),
                          "user_id_configured": bool(config.user_id)}, indent=2))
        return 0
    print(json.dumps(download_kaufland_receipts(config), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
