#!/usr/bin/env python3
"""Import the latest (or selected) DRP into the current Resolve library."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
DEFAULT_PROJECTS_DIR = Path("/Volumes/TASTY/RATTLE/project/projects")
VERSION_RE = re.compile(r"^(?P<base>.*?)[_\-\s]v(?P<num>\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class DrpCandidate:
    path: Path
    base: str
    version: int


def load_resolve_script_module():
    module_dirs = []
    for path in MODULE_PATH_CANDIDATES:
        parent = str(Path(path).parent)
        if Path(parent).exists():
            module_dirs.append(parent)

    for module_dir in reversed(module_dirs):
        if module_dir in sys.path:
            sys.path.remove(module_dir)
        sys.path.insert(0, module_dir)

    if SCRIPT_MODULE_NAME in sys.modules:
        mod = sys.modules[SCRIPT_MODULE_NAME]
        if hasattr(mod, "scriptapp"):
            return mod
        del sys.modules[SCRIPT_MODULE_NAME]

    try:
        mod = importlib.import_module(SCRIPT_MODULE_NAME)
        if hasattr(mod, "scriptapp"):
            return mod
    except ImportError:
        pass

    for path in MODULE_PATH_CANDIDATES:
        module_path = Path(path)
        if not module_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(SCRIPT_MODULE_NAME, module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "scriptapp"):
                return module

    raise RuntimeError("Could not load DaVinciResolveScript with scriptapp().")


def parse_version(stem: str) -> tuple[str, int]:
    m = VERSION_RE.match(stem.strip())
    if not m:
        return stem.strip(), -1
    return (m.group("base") or "").strip(), int(m.group("num"))


def collect_candidates(projects_dir: Path) -> list[DrpCandidate]:
    out = []
    for p in sorted(projects_dir.glob("*.drp")):
        base, version = parse_version(p.stem)
        out.append(DrpCandidate(path=p, base=base, version=version))
    return out


def choose_candidate(candidates: list[DrpCandidate], name: str) -> DrpCandidate:
    if not candidates:
        raise RuntimeError("No .drp files found.")

    if name:
        target = name.removesuffix(".drp").strip()

        # exact stem match first
        exact = [c for c in candidates if c.path.stem == target]
        if exact:
            return exact[0]

        # if target looks like base name, pick latest version within that base
        filtered = [c for c in candidates if c.base.lower() == target.lower()]
        if filtered:
            return sorted(filtered, key=lambda c: (c.version, c.path.stat().st_mtime), reverse=True)[0]

        raise RuntimeError(f"No .drp found for --name '{name}'.")

    # default: latest version across all candidates; tie-break by mtime
    versioned = [c for c in candidates if c.version >= 0]
    if versioned:
        return sorted(versioned, key=lambda c: (c.version, c.path.stat().st_mtime), reverse=True)[0]

    # fallback: newest file by mtime
    return sorted(candidates, key=lambda c: c.path.stat().st_mtime, reverse=True)[0]


def build_parser():
    p = argparse.ArgumentParser(description="Import latest or selected DRP into Resolve library.")
    p.add_argument(
        "--projects-dir",
        default=str(DEFAULT_PROJECTS_DIR),
        help="Folder containing .drp files (default: %(default)s).",
    )
    p.add_argument(
        "--name",
        default="",
        help="Optional DRP stem or base name to import (e.g. RATTLE_v001 or RATTLE).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview selected DRP and target library without importing.",
    )
    return p


def main():
    args = build_parser().parse_args()
    projects_dir = Path(args.projects_dir).expanduser().resolve()
    if not projects_dir.exists() or not projects_dir.is_dir():
        raise RuntimeError(f"Projects dir not found: {projects_dir}")

    candidates = collect_candidates(projects_dir)
    chosen = choose_candidate(candidates, args.name)

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    pm = resolve.GetProjectManager()
    if not pm:
        raise RuntimeError("Could not access Resolve ProjectManager.")

    current_db = getattr(pm, "GetCurrentDatabase", lambda: {})()
    db_name = current_db.get("DbName") if isinstance(current_db, dict) else "<unknown>"

    print("=== Import Project DRP ===")
    print(f"Library      : {db_name}")
    print(f"Projects dir : {projects_dir}")
    print(f"Selected DRP : {chosen.path}")
    print(f"Dry run      : {'yes' if args.dry_run else 'no'}")
    print("==========================")

    if args.dry_run:
        return

    import_fn = getattr(pm, "ImportProject", None)
    if not callable(import_fn):
        raise RuntimeError("ProjectManager.ImportProject is unavailable in this Resolve build.")

    ok = bool(import_fn(str(chosen.path)))
    if not ok:
        raise RuntimeError(f"Resolve failed to import project: {chosen.path}")

    print("Import result: success")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
