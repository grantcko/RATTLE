#!/usr/bin/env python3
"""Open the latest version of a Resolve project in the active library/folder.

Default behavior:
- Launch DaVinci Resolve
- Use the currently active project library (database)
- Use the currently open project name as the seed name
- Find the latest version in the current folder tree
- Load that project

If no project is currently open, pass --project-name.
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import importlib.util
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
RESOLVE_APP_NAME = "DaVinci Resolve"
GENERIC_PROJECT_NAMES = {"untitled", "untitled project", "new project"}

VERSION_PATTERNS = [
    re.compile(r"^(?P<base>.*?)[\s._-]*(?:v|ver|version)[\s._-]*(?P<ver>\d{1,5})$", re.IGNORECASE),
    re.compile(r"^(?P<base>.*?)[\s._-]+(?P<ver>\d{2,5})$", re.IGNORECASE),
]


@dataclass(frozen=True)
class ProjectCandidate:
    name: str
    version: int
    depth: int


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: ProjectCandidate
    score: float


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


def call_method(obj, *names: str, default=None):
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn
    if default is not None:
        return default
    raise AttributeError(f"None of methods exist on object: {', '.join(names)}")


def normalize_base(name: str) -> str:
    base, _ = split_version(name)
    return re.sub(r"[\s._-]+", " ", base.strip().lower())


def split_version(name: str) -> tuple[str, int]:
    candidate = (name or "").strip()
    for pat in VERSION_PATTERNS:
        match = pat.match(candidate)
        if not match:
            continue
        base = (match.group("base") or "").strip()
        ver = int(match.group("ver"))
        if base:
            return base, ver
    return candidate, -1


def default_drp_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "project" / "projects"


def latest_drp_seed_name(drp_dir: Path) -> str:
    files = sorted(
        [p for p in drp_dir.glob("*.drp") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return ""
    return files[0].stem.strip()


def launch_resolve():
    subprocess.run(["open", "-a", RESOLVE_APP_NAME], check=True)


def connect_resolve(timeout_seconds: int):
    resolve_module = load_resolve_script_module()
    deadline = time.time() + timeout_seconds
    last_error = None

    while time.time() < deadline:
        try:
            resolve = resolve_module.scriptapp("Resolve")
            if resolve:
                return resolve
        except Exception as exc:  # pragma: no cover
            last_error = exc
        time.sleep(1)

    if last_error:
        raise RuntimeError(f"Could not connect to Resolve before timeout. Last error: {last_error}")
    raise RuntimeError("Could not connect to Resolve before timeout.")


def set_library_if_requested(pm, library_name: str):
    if not library_name:
        return

    get_db_list = call_method(pm, "GetDatabaseList")
    set_current_db = call_method(pm, "SetCurrentDatabase")

    db_list = list(get_db_list() or [])
    if not db_list:
        raise RuntimeError("Resolve returned no project libraries/databases.")

    normalized_target = library_name.strip().lower()
    for db in db_list:
        if not isinstance(db, dict):
            continue
        db_name = str(db.get("DbName", "")).strip()
        if db_name.lower() == normalized_target:
            if not set_current_db(db):
                raise RuntimeError(f"Failed to switch to library '{library_name}'.")
            return

    known = ", ".join(sorted({str(d.get("DbName", "")) for d in db_list if isinstance(d, dict)}))
    raise RuntimeError(f"Library '{library_name}' not found. Available: {known}")


def collect_project_names_recursive(pm) -> list[ProjectCandidate]:
    get_folders = call_method(pm, "GetFolderListInCurrentFolder")
    get_projects = call_method(pm, "GetProjectListInCurrentFolder")
    open_folder = call_method(pm, "OpenFolder")
    goto_parent = call_method(pm, "GotoParentFolder")
    goto_root = call_method(pm, "GotoRootFolder")

    if not goto_root():
        raise RuntimeError("Failed to jump to root folder in project library.")

    out: list[ProjectCandidate] = []

    def walk(depth: int):
        names = list(get_projects() or [])
        for name in names:
            if not isinstance(name, str):
                continue
            _, ver = split_version(name)
            out.append(ProjectCandidate(name=name, version=ver, depth=depth))

        folders = list(get_folders() or [])
        for folder_name in folders:
            if not isinstance(folder_name, str):
                continue
            if not open_folder(folder_name):
                continue
            walk(depth + 1)
            goto_parent()

    walk(0)
    return out


def score_candidates(candidates: list[ProjectCandidate], seed_name: str) -> list[ScoredCandidate]:
    seed_base = normalize_base(seed_name)
    exact_base = [c for c in candidates if normalize_base(c.name) == seed_base]
    if exact_base:
        return [ScoredCandidate(candidate=c, score=1.0) for c in exact_base]

    seed_compact = re.sub(r"[^a-z0-9]+", "", seed_base)
    scored: list[ScoredCandidate] = []
    for c in candidates:
        base = normalize_base(c.name)
        compact = re.sub(r"[^a-z0-9]+", "", base)
        score = difflib.SequenceMatcher(None, seed_compact, compact).ratio()
        if seed_compact and compact and (seed_compact in compact or compact in seed_compact):
            score = max(score, 0.95)
        scored.append(ScoredCandidate(candidate=c, score=score))

    if not scored:
        raise RuntimeError("No projects found in the current library.")

    top_score = max(s.score for s in scored)
    if top_score < 0.55:
        raise RuntimeError(f"No close project match for '{seed_name}' in the current library.")

    return [s for s in scored if s.score >= top_score - 0.10]


def sort_scored(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    return sorted(
        scored,
        key=lambda s: (
            s.candidate.version,
            s.score,
            -s.candidate.depth,
            s.candidate.name.lower(),
        ),
        reverse=True,
    )


def choose_latest_candidate(candidates: list[ProjectCandidate], seed_name: str) -> ProjectCandidate:
    scored = sort_scored(score_candidates(candidates, seed_name))
    return scored[0].candidate


def choose_candidate(
    candidates: list[ProjectCandidate], seed_name: str
) -> ProjectCandidate:
    scored = sort_scored(score_candidates(candidates, seed_name))
    return scored[0].candidate


def resolve_seed_project_name(pm, explicit_name: str, drp_dir: Path) -> str:
    if explicit_name:
        return explicit_name.strip()

    current_project = call_method(pm, "GetCurrentProject", default=lambda: None)()
    if current_project:
        get_name = getattr(current_project, "GetName", None)
        if callable(get_name):
            name = (get_name() or "").strip()
            if name and name.strip().lower() not in GENERIC_PROJECT_NAMES:
                return name

    drp_seed = latest_drp_seed_name(drp_dir)
    if drp_seed:
        return drp_seed

    raise RuntimeError("No usable seed project name found. Pass --project-name.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Open latest version of a Resolve project in the active library."
    )
    parser.add_argument(
        "--project-name",
        default="",
        help="Seed project name. If omitted, uses current open project's name.",
    )
    parser.add_argument(
        "--library",
        default="",
        help="Optional Resolve project library/database name to switch to before searching.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Seconds to wait for Resolve scripting connection (default: %(default)s).",
    )
    parser.add_argument(
        "--drp-dir",
        default=str(default_drp_dir()),
        help="Folder used for fallback seed name from latest .drp (default: %(default)s).",
    )
    return parser


def main():
    args = build_parser().parse_args()

    launch_resolve()
    resolve = connect_resolve(timeout_seconds=args.timeout)
    pm = resolve.GetProjectManager()
    if not pm:
        raise RuntimeError("Could not get Resolve ProjectManager.")

    set_library_if_requested(pm, args.library)

    current_db = call_method(pm, "GetCurrentDatabase", default=lambda: {})()
    db_name = current_db.get("DbName") if isinstance(current_db, dict) else None

    drp_dir = Path(args.drp_dir).expanduser().resolve()
    seed_name = resolve_seed_project_name(pm, args.project_name, drp_dir)
    candidates = collect_project_names_recursive(pm)
    latest = choose_candidate(candidates, seed_name)

    load_project = call_method(pm, "LoadProject")
    loaded = load_project(latest.name)
    if not loaded:
        raise RuntimeError(f"Resolve failed to open project '{latest.name}'.")

    print("=== Open Latest Resolve Project ===")
    print(f"Library      : {db_name or '<unknown>'}")
    print(f"Seed project : {seed_name}")
    print(f"Opened       : {latest.name}")
    print(f"Version      : {latest.version if latest.version >= 0 else 'unversioned'}")
    print("===================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
