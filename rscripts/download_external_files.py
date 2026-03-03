#!/usr/bin/env python3
"""Download Archive.org items from a simple list, then clean temporary files.

Flow:
1) Resolve item identifiers from an Archive.org simple list name
2) Write identifiers to a temp itemlist file
3) Run `ia download --itemlist <tempfile>`
4) Remove temp itemlist file (cleanup)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def require_ia() -> str:
    ia_path = shutil.which("ia")
    if not ia_path:
        raise RuntimeError("'ia' CLI not found in PATH.")
    return ia_path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def list_identifiers(list_name: str) -> list[str]:
    # ia simplelists prints children entries for the list.
    proc = run(["ia", "simplelists", "-c", "-l", list_name], check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to query simple list '{list_name}'.\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]

    # Be robust to different output styles; first token is usually identifier.
    identifiers: list[str] = []
    seen = set()
    for ln in lines:
        token = ln.split()[0].strip()
        if not token or token.startswith("#"):
            continue
        # Skip obvious non-identifier labels if present.
        if token.lower() in {"identifier", "item", "children", "count"}:
            continue
        if token not in seen:
            seen.add(token)
            identifiers.append(token)

    if not identifiers:
        raise RuntimeError(
            f"No identifiers found in simple list '{list_name}'.\n"
            f"Raw output:\n{proc.stdout}"
        )

    return identifiers


def list_identifiers_from_url(list_url: str) -> list[str]:
    parsed = urlparse(list_url)
    if parsed.scheme != "https":
        raise RuntimeError("List URL must use https.")
    if parsed.netloc not in {"archive.org", "www.archive.org"}:
        raise RuntimeError("List URL must be on archive.org.")

    parts = [p for p in parsed.path.split("/") if p]
    # Expected: /details/@user/lists/<id>/<slug>
    if len(parts) < 4 or parts[0] != "details" or parts[2] != "lists":
        raise RuntimeError(
            "List URL format not recognized. Expected "
            "https://archive.org/details/@user/lists/<id>/<slug>"
        )

    # Sanity check: ensure the provided URL itself is reachable.
    req = Request(list_url, headers={"User-Agent": "RATTLE/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise RuntimeError(f"List URL is not reachable (HTTP {status}): {list_url}")
    except Exception as exc:
        raise RuntimeError(f"List URL sanity check failed: {list_url} ({exc})") from exc

    user = parts[1]
    list_id = parts[3]
    api_url = f"https://archive.org/services/users/{user}/lists/{list_id}"
    with urlopen(api_url, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    if not payload.get("success"):
        raise RuntimeError(f"List API returned non-success for URL: {list_url}")
    value = payload.get("value") or {}
    members = value.get("members") or []
    out = []
    seen = set()
    for member in members:
        ident = str(member.get("identifier", "")).strip()
        if ident and ident not in seen:
            seen.add(ident)
            out.append(ident)
    if not out:
        raise RuntimeError(f"No identifiers found in list URL: {list_url}")
    return out


def build_download_cmd(itemlist_file: Path, args) -> list[str]:
    cmd = ["ia", "download", "--itemlist", str(itemlist_file)]
    if args.destdir:
        cmd += ["--destdir", args.destdir]
    if args.glob:
        cmd += ["--glob", args.glob]
    if args.format:
        for fmt in args.format:
            cmd += ["--format", fmt]
    if args.ignore_existing:
        cmd += ["--ignore-existing"]
    if args.dry_run:
        cmd += ["--dry-run"]
    return cmd


def main():
    ap = argparse.ArgumentParser(
        description="Download all items from an Archive.org simple list and clean temp list file."
    )
    ap.add_argument("list_name", nargs="?", default="", help="Archive.org simple list name")
    ap.add_argument(
        "--list-url",
        default="",
        help="Archive.org user list URL (e.g. https://archive.org/details/@user/lists/1/name).",
    )
    ap.add_argument("--destdir", default="", help="Destination folder for downloads")
    ap.add_argument("--glob", default="", help="Filename glob filter (ia --glob)")
    ap.add_argument("--format", action="append", default=[], help="File format filter (repeatable)")
    ap.add_argument("--ignore-existing", action="store_true", help="Clobber files already downloaded")
    ap.add_argument("--dry-run", action="store_true", help="Print download URLs only")
    args = ap.parse_args()

    ia_path = require_ia()
    print("=== Download External Files ===")
    print(f"ia path      : {ia_path}")
    print(f"list name    : {args.list_name or '<none>'}")
    print(f"list url     : {args.list_url or '<none>'}")
    print(f"destdir      : {args.destdir or '<default>'}")
    print(f"dry run      : {'yes' if args.dry_run else 'no'}")

    if args.list_url:
        identifiers = list_identifiers_from_url(args.list_url)
    elif args.list_name:
        identifiers = list_identifiers(args.list_name)
    else:
        raise RuntimeError("Provide either list_name or --list-url.")
    print(f"items found  : {len(identifiers)}")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="ia-itemlist-", delete=False)
    tmp_path = Path(tmp.name)
    try:
        for item in identifiers:
            tmp.write(item + "\n")
        tmp.flush()
        tmp.close()

        cmd = build_download_cmd(tmp_path, args)
        print(f"download cmd : {' '.join(cmd)}")

        dl = run(cmd, check=False)
        print(dl.stdout, end="")
        if dl.stderr:
            print(dl.stderr, end="")
        if dl.returncode != 0:
            raise RuntimeError(f"ia download failed with code {dl.returncode}")

    finally:
        if tmp_path.exists():
            tmp_path.unlink()
            print(f"cleanup      : removed temp itemlist {tmp_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
