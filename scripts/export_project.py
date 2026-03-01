#!/usr/bin/env python3
"""Export current Resolve project DRP without path scrubbing or relinking."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
DEFAULT_EXPORT_DIR = Path("/Volumes/TASTY/RATTLE/project")
TIMELINE_BIN_NAME = "timelines"
GENERIC_USER_DIR_NAMES = {"shared", "public", "guest", "users"}
REQUIRED_00_BINS = {"00-source"}


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


def folder_name(folder):
    try:
        return folder.GetName() or "<unnamed>"
    except Exception:
        return "<unknown>"


def subfolders(folder):
    fn = getattr(folder, "GetSubFolderList", None)
    if callable(fn):
        return list(fn() or [])
    return []


def walk_folders(folder):
    yield folder
    for child in subfolders(folder):
        yield from walk_folders(child)


def clips(folder):
    fn = getattr(folder, "GetClipList", None)
    if callable(fn):
        return list(fn() or [])
    return []


def clip_name(clip):
    fn = getattr(clip, "GetName", None)
    if callable(fn):
        try:
            return fn() or "<unnamed-clip>"
        except Exception:
            return "<unknown-clip>"
    return "<unknown-clip>"


def clip_type(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        try:
            typ = get_prop("Type")
            if isinstance(typ, str):
                return typ.strip()
        except Exception:
            pass
    return ""


def clip_file_path(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        for key in ("File Path", "Clip Path"):
            try:
                val = get_prop(key)
            except Exception:
                val = ""
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def user_markers():
    markers = set()
    for env_key in ("USER", "LOGNAME", "USERNAME"):
        val = os.getenv(env_key, "").strip()
        if val:
            markers.add(val.lower())
    try:
        home_name = Path.home().name.strip()
        if home_name:
            markers.add(home_name.lower())
    except Exception:
        pass
    try:
        host = os.uname().nodename.strip()
        if host:
            markers.add(host.lower())
    except Exception:
        pass
    return {m for m in markers if len(m) >= 3}


def find_user_specific_name_issue(text, markers):
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None

    low = stripped.lower()
    for marker in markers:
        if marker in low:
            return f"contains local user/host marker '{marker}'"

    for part in re_split_path(stripped):
        pl = part.lower()
        if pl in {"users", "home"}:
            continue
        if pl in GENERIC_USER_DIR_NAMES:
            continue
        if low.startswith("/users/"):
            segs = [p for p in stripped.split("/") if p]
            if len(segs) >= 2 and part == segs[1]:
                return f"contains user-home path segment '{part}'"
        if low.startswith("/home/"):
            segs = [p for p in stripped.split("/") if p]
            if len(segs) >= 2 and part == segs[1]:
                return f"contains user-home path segment '{part}'"
    return None


def re_split_path(p: str):
    return [x for x in p.replace("\\", "/").split("/") if x]


def normalize_bin_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def is_00_bin(name: str) -> bool:
    return normalize_bin_name(name).startswith("00")


def print_compact_examples(values, limit=5):
    shown = values[:limit]
    for value in shown:
        print(f"  - {value}")
    if len(values) > limit:
        print(f"  - ... and {len(values) - limit} more")


def run_non_link_checks(root, timeline_bin):
    child_bins = subfolders(timeline_bin)
    bad_items = []
    user_name_issues = []
    markers = user_markers()

    for c in clips(timeline_bin):
        typ = clip_type(c).lower()
        if typ != "timeline":
            bad_items.append((clip_name(c), clip_type(c) or "<unknown-type>"))

    for folder in walk_folders(root):
        folder_path = folder_name(folder)
        for c in clips(folder):
            c_name = clip_name(c)
            c_type = clip_type(c) or "<unknown-type>"
            c_path = clip_file_path(c)

            issue = find_user_specific_name_issue(c_name, markers)
            if issue:
                user_name_issues.append((folder_path, c_name, c_type, "item name", issue))

            path_basename = Path(c_path).name if c_path else ""
            if path_basename:
                issue = find_user_specific_name_issue(path_basename, markers)
                if issue:
                    user_name_issues.append(
                        (folder_path, c_name, c_type, "linked/imported file name", issue)
                    )

    root_children = subfolders(root)
    zero_zero_bins = [folder_name(f) for f in root_children if is_00_bin(folder_name(f))]
    zero_zero_bins_norm = {normalize_bin_name(n) for n in zero_zero_bins}
    disallowed_00_bins = [
        n for n in zero_zero_bins if normalize_bin_name(n) not in REQUIRED_00_BINS
    ]
    missing_required_00_bins = [
        n for n in sorted(REQUIRED_00_BINS) if n not in zero_zero_bins_norm
    ]

    print("\n--- Validation (non-link checks) ---")
    failed = False
    if child_bins:
        print(f"Timeline folder contains sub-bins ({len(child_bins)}). Finalize/move them before export.")
        print_compact_examples([folder_name(child) for child in child_bins])
        failed = True

    if bad_items:
        print(f"Timeline folder contains non-timeline items ({len(bad_items)}).")
        print_compact_examples([f"{name} :: {typ}" for name, typ in bad_items])
        failed = True

    if user_name_issues:
        print(
            f"User-specific naming found in item names or linked/imported file names ({len(user_name_issues)})."
        )
        compact = [f"{item_name} :: {field_name} ({reason})" for _, item_name, _, field_name, reason in user_name_issues]
        print_compact_examples(compact)
        failed = True

    if disallowed_00_bins or missing_required_00_bins:
        print("Invalid 00-bin setup. The only allowed 00 bin should be 00-SOURCE.")
        if disallowed_00_bins:
            print(f"Disallowed 00 bins found ({len(disallowed_00_bins)}):")
            print_compact_examples(disallowed_00_bins)
        if missing_required_00_bins:
            print(f"Missing required 00 bins ({len(missing_required_00_bins)}):")
            print_compact_examples(missing_required_00_bins)
        failed = True

    if not failed:
        print("Non-link checks passed.")
    return not failed


def find_timeline_bin(root):
    exact = [f for f in walk_folders(root) if folder_name(f) == TIMELINE_BIN_NAME]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(f"Multiple bins named '{TIMELINE_BIN_NAME}' found. Please disambiguate.")

    candidates = []
    for f in walk_folders(root):
        for c in clips(f):
            if clip_type(c).lower() == "timeline":
                candidates.append(f)
                break

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError("Could not auto-detect a timeline bin (no bin with timeline items found).")
    names = ", ".join(sorted({folder_name(f) for f in candidates}))
    raise RuntimeError(
        "Could not auto-detect a single timeline bin; multiple bins contain timelines: "
        f"{names}"
    )


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def check_export_path_git_safety(export_path: Path):
    repo = repo_root()
    rel_s = None
    in_repo = True
    try:
        rel = export_path.resolve().relative_to(repo.resolve())
        rel_s = rel.as_posix()
    except Exception:
        in_repo = False

    exists = export_path.exists()
    tracked = False
    dirty = False

    if in_repo and rel_s:
        tracked_probe = run_git(repo, ["ls-files", "--error-unmatch", rel_s])
        if tracked_probe.returncode == 0:
            tracked = True
            status = run_git(repo, ["status", "--porcelain", "--", rel_s])
            if status.returncode == 0 and status.stdout.strip():
                dirty = True

    return {
        "exists": exists,
        "tracked": tracked,
        "dirty": dirty,
        "relative_path": rel_s,
        "in_repo": in_repo,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export current project DRP without relinking or scrubbing.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--export-dir",
        default=str(DEFAULT_EXPORT_DIR),
        help=f"Directory to write exported DRP file. Default: {DEFAULT_EXPORT_DIR}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip validation and git-safety blockers and continue anyway.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview operations without exporting.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    export_dir = Path(args.export_dir).expanduser()

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")
    pm = resolve.GetProjectManager()
    if not pm:
        raise RuntimeError("Could not access Project Manager.")
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current project is open.")

    project_name = project.GetName() or ""
    if not project_name:
        raise RuntimeError("Current project has no name.")

    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Could not access Media Pool in current project.")
    root = media_pool.GetRootFolder()
    if not root:
        raise RuntimeError("Could not access Media Pool root in current project.")

    timeline_bin = find_timeline_bin(root)
    export_path = export_dir / f"{project_name}.drp"

    print("=== Export Project ===")
    print(f"Project      : {project_name}")
    print(f"Export dir   : {export_dir}")
    print(f"DRP path     : {export_path}")
    print(f"Force        : {'yes' if args.force else 'no'}")
    print(f"Dry run      : {'yes' if args.dry_run else 'no'}")
    print("======================")

    non_link_ok = run_non_link_checks(root, timeline_bin)
    if not non_link_ok and not args.force:
        raise RuntimeError("Non-link export checks failed. Re-run with --force to continue anyway.")

    export_safety = check_export_path_git_safety(export_path)
    print("\n--- Export Path Check ---")
    print(f"Inside repo    : {'yes' if export_safety['in_repo'] else 'no'}")
    print(f"Exists         : {'yes' if export_safety['exists'] else 'no'}")
    print(f"Git tracked    : {'yes' if export_safety['tracked'] else 'no'}")
    print(f"Git dirty      : {'yes' if export_safety['dirty'] else 'no'}")
    if export_safety["dirty"] and not args.force:
        dirty_path = export_safety["relative_path"] or str(export_path)
        raise RuntimeError(
            f"Existing tracked DRP has uncommitted changes ({dirty_path}). "
            "Commit/stash or re-run with --force."
        )
    if export_safety["exists"] and not export_safety["tracked"] and not args.force:
        unsafe_path = export_safety["relative_path"] or str(export_path)
        raise RuntimeError(
            f"Existing DRP is not git-tracked ({unsafe_path}). "
            "Re-run with --force to allow overwrite."
        )

    if args.dry_run:
        print("\nDry run: skipping export.")
        return

    export_dir.mkdir(parents=True, exist_ok=True)
    export_fn = getattr(pm, "ExportProject", None)
    if not callable(export_fn):
        raise RuntimeError("ProjectManager.ExportProject is unavailable in this Resolve build.")
    if not export_fn(project_name, str(export_path)):
        raise RuntimeError(f"Failed to export DRP to {export_path}")

    print("\n=== Result ===")
    print(f"DRP export    : {export_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user (Ctrl-C).", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
