#!/usr/bin/env python3
"""Validate the timeline bin is export-ready.

Checks:
1) No sub-bins inside the timeline bin.
2) Only timeline items are present in the timeline bin.
3) No user-specific names in imported/linked file names or clip item names.
4) No linked proxy/full-res media items.
5) Timeline items are unlinked (for easier handoff).
"""

from __future__ import annotations

import importlib
import importlib.util
import argparse
import os
import re
import sys
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
TIMELINE_BIN_NAME = "timelines"  # Change if your timeline bin is named differently.
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
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


def clip_properties(clip):
    get_prop = getattr(clip, "GetClipProperty", None)
    if callable(get_prop):
        try:
            props = get_prop()
            if isinstance(props, dict):
                return props
        except Exception:
            pass
    return {}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate the timeline bin is export-ready.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full per-item details for each failed check.",
    )
    return parser.parse_args()


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
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", stripped):
        return "contains email-like token"

    for marker in markers:
        if marker in low:
            return f"contains local user/host marker '{marker}'"

    for part in re.split(r"[\\/]+", stripped):
        if not part:
            continue
        pl = part.lower()
        if pl in {"users", "home"}:
            continue
        if pl in GENERIC_USER_DIR_NAMES:
            continue
        if low.startswith("/users/") and part == stripped.split("/")[2]:
            # macOS user home segment in /Users/<name>/...
            return f"contains user-home path segment '{part}'"
        if low.startswith("/home/") and part == stripped.split("/")[2]:
            return f"contains user-home path segment '{part}'"
    return None


def has_linked_source_media(clip):
    props = clip_properties(clip)
    linked_details = []
    seen = set()

    # 1) Non-proxy linked-path style properties.
    for key, value in props.items():
        key_low = str(key).lower()
        if "linked" not in key_low:
            continue
        if "proxy" in key_low:
            continue
        value_text = str(value).strip()
        if not value_text:
            continue
        value_low = value_text.lower()
        if value_low in {"none", "no", "false", "0", "not linked", "unlinked", "n/a"}:
            continue
        row = (str(key), value_text)
        if row not in seen:
            linked_details.append(row)
            seen.add(row)

    return linked_details


def has_linked_proxy_media(clip):
    props = clip_properties(clip)
    linked_details = []
    for key, value in props.items():
        key_low = str(key).lower()
        if "proxy" not in key_low:
            continue
        value_text = str(value).strip()
        if not value_text:
            continue
        value_low = value_text.lower()
        if value_low in {"none", "no", "false", "0", "not linked", "unlinked", "n/a"}:
            continue
        linked_details.append((str(key), value_text))
    return linked_details


def print_compact_examples(values, limit=5):
    shown = values[:limit]
    for value in shown:
        print(f"  - {value}")
    if len(values) > limit:
        print(f"  - ... and {len(values) - limit} more")


def print_section(title: str):
    print(f"\n--- {title} ---")


def normalize_bin_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def is_00_bin(name: str) -> bool:
    return bool(re.match(r"^00\b", (name or "").strip().lower()))


def main():
    args = parse_args()
    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    pm = resolve.GetProjectManager()
    if not pm:
        raise RuntimeError("Could not get Project Manager.")

    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current project is open.")

    media_pool = project.GetMediaPool()
    if not media_pool:
        raise RuntimeError("Could not access Media Pool.")

    root = media_pool.GetRootFolder()
    if not root:
        raise RuntimeError("Could not access Media Pool root folder.")

    matching = [f for f in walk_folders(root) if folder_name(f) == TIMELINE_BIN_NAME]
    if not matching:
        raise RuntimeError(f"Timeline bin '{TIMELINE_BIN_NAME}' not found.")
    if len(matching) > 1:
        raise RuntimeError(f"Multiple bins named '{TIMELINE_BIN_NAME}' found. Please disambiguate.")

    timeline_bin = matching[0]
    child_bins = subfolders(timeline_bin)
    bad_items = []
    user_name_issues = []
    linked_media_issues = []
    linked_proxy_issues = []

    print("=== Export Check ===")
    print(f"Project      : {project.GetName()}")
    print(f"Timeline Bin : {TIMELINE_BIN_NAME}")
    print("====================")

    for c in clips(timeline_bin):
        typ = clip_type(c).lower()
        if typ != "timeline":
            bad_items.append((clip_name(c), clip_type(c) or "<unknown-type>"))

    markers = user_markers()
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

            link_details = has_linked_source_media(c)
            if link_details:
                linked_media_issues.append((folder_path, c_name, c_type, link_details))
            proxy_details = has_linked_proxy_media(c)
            if proxy_details:
                linked_proxy_issues.append((folder_path, c_name, c_type, proxy_details))

    root_children = subfolders(root)
    zero_zero_bins = [folder_name(f) for f in root_children if is_00_bin(folder_name(f))]
    zero_zero_bins_norm = {normalize_bin_name(n) for n in zero_zero_bins}
    disallowed_00_bins = [
        n for n in zero_zero_bins if normalize_bin_name(n) not in REQUIRED_00_BINS
    ]
    missing_required_00_bins = [
        n for n in sorted(REQUIRED_00_BINS) if n not in zero_zero_bins_norm
    ]
    out_storage_bins = [n for n in zero_zero_bins if "out storage" in normalize_bin_name(n)]

    failed = False
    print_section("Validation")

    if child_bins:
        print(f"Timeline folder contains sub-bins ({len(child_bins)}). Finalize/move them before export.")
        child_names = [folder_name(child) for child in child_bins]
        print_compact_examples(child_names)
        failed = True

    if bad_items:
        print(f"Timeline folder contains non-timeline items ({len(bad_items)}).")
        if args.verbose:
            for name, typ in bad_items:
                print(f"  - {name} :: {typ}")
        else:
            print_compact_examples([f"{name} :: {typ}" for name, typ in bad_items])
        failed = True

    if user_name_issues:
        print(
            f"User-specific naming found in item names or linked/imported file names ({len(user_name_issues)})."
        )
        if args.verbose:
            for folder_path, item_name, item_type, field_name, reason in user_name_issues:
                print(f"  - [{folder_path}] {item_name} :: {item_type} :: {field_name} ({reason})")
        else:
            compact = [f"{item_name} :: {field_name} ({reason})" for _, item_name, _, field_name, reason in user_name_issues]
            print_compact_examples(compact)
        failed = True

    if linked_media_issues:
        print(
            f"Linked source media file-path references found ({len(linked_media_issues)}). "
            "Unlink before handoff."
        )
        if args.verbose:
            for folder_path, item_name, item_type, details in linked_media_issues:
                print(f"  - [{folder_path}] {item_name} :: {item_type}")
                for key, val in details:
                    print(f"      {key}: {val}")
        else:
            print_compact_examples([f"{name} :: {typ}" for _, name, typ, _ in linked_media_issues])
        failed = True

    if linked_proxy_issues:
        print(
            f"Linked proxy media references found ({len(linked_proxy_issues)}). "
            "Unlink proxy media before handoff."
        )
        if args.verbose:
            for folder_path, item_name, item_type, details in linked_proxy_issues:
                print(f"  - [{folder_path}] {item_name} :: {item_type}")
                for key, val in details:
                    print(f"      {key}: {val}")
        else:
            print_compact_examples([f"{name} :: {typ}" for _, name, typ, _ in linked_proxy_issues])
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

    if out_storage_bins:
        print("Warning: OUT STORAGE bin detected.")
        print("All out storage should be copied to 00-SOURCE or to cloud storage.")
        if args.verbose:
            print_compact_examples(out_storage_bins, limit=len(out_storage_bins))
        failed = True

    if failed:
        sys.exit(1)

    print(
        "Timeline bin export check passed: no sub-bins, timeline-only bin, "
        "clean names, and no linked source media references."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user (Ctrl-C).", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
