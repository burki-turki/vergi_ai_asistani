#!/usr/bin/env python3
"""Operator-only local key custody initialization and rotation CLI."""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import key_custody


def _new_key_id() -> str:
    return "local-" + secrets.token_hex(16)


def initialize_local_key_file() -> tuple[Path, str]:
    key_id = _new_key_id()

    def create() -> key_custody._CustodyMaterial:
        return key_custody._CustodyMaterial(
            current_key_id=key_id,
            keys={key_id: secrets.token_bytes(32)},
            server_pepper=secrets.token_bytes(32),
        )

    path = key_custody.initialize_secure_document(create)
    return path, key_id


def rotate_current_key() -> tuple[Path, str]:
    def transform(material: key_custody._CustodyMaterial):
        key_id = _new_key_id()
        while key_id in material.keys:
            key_id = _new_key_id()
        keys = dict(material.keys)
        keys[key_id] = secrets.token_bytes(32)
        return (
            key_custody._CustodyMaterial(key_id, keys, material.server_pepper),
            key_id,
        )

    return key_custody.mutate_secure_document(transform)


def rotate_server_pepper() -> Path:
    def transform(material: key_custody._CustodyMaterial):
        return (
            key_custody._CustodyMaterial(
                material.current_key_id,
                dict(material.keys),
                secrets.token_bytes(32),
            ),
            None,
        )

    path, _ = key_custody.mutate_secure_document(transform)
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local development key custody.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("initialize", help="Create a new local custody file.")
    subparsers.add_parser("rotate-key", help="Rotate the AES key and preserve older keys.")
    subparsers.add_parser("rotate-pepper", help="Rotate the server pepper separately.")
    return parser


def _emit_committed(operation: str, path: Path, key_id: str | None) -> None:
    if operation == "initialize":
        print(f"initialized local key custody at {path}; current_key_id={key_id}")
    elif operation == "rotate-key":
        print(
            f"rotated current AES key at {path}; current_key_id={key_id}; "
            "previous keys preserved"
        )
    else:
        print(
            "WARNING: committed server-pepper rotation invalidates existing "
            "sessions' CSRF derivations."
        )
        print(f"rotated server pepper at {path}")


def _emit_reporting_failure(operation: str) -> None:
    if operation == "rotate-pepper":
        print(
            "WARNING: server-pepper rotation COMMITTED and invalidates existing "
            "sessions' CSRF derivations.",
            file=sys.stderr,
        )
    print(
        f"COMMITTED_WITH_REPORTING_ERROR: {operation} changed custody bytes; "
        "do not retry as though it was unapplied.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.operation == "initialize":
            path, key_id = initialize_local_key_file()
        elif args.operation == "rotate-key":
            path, key_id = rotate_current_key()
        else:
            path = rotate_server_pepper()
            key_id = None
    except (key_custody.KeyCustodyError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        _emit_committed(args.operation, path, key_id)
    except Exception:
        try:
            _emit_reporting_failure(args.operation)
        except Exception:
            pass
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
