#!/usr/bin/env python3
"""Export the currently open Resolve timeline to project/timelines as a .drt."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path

SCRIPT_MODULE_NAME = "DaVinciResolveScript"
MODULE_PATH_CANDIDATES = [
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py",
    os.path.expandvars(
        "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
    ),
]
DRT_EXPORT_TYPE = 1
VERSION_TOKEN_RE = re.compile(r"(?P<prefix>.*?)(?P<sep>[_\-\s])v(?P<num>\d+)(?P<suffix>.*)$", re.IGNORECASE)
LEADING_NUM_RE = re.compile(r"^(?P<num>\d+)(?:[-_\s].*)?$")
NUM_SUFFIX_RE = re.compile(r"^(?P<num>\d+)(?P<suffix>[-_\s].+)?$")


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


def sanitize_filename(value: str) -> str:
    safe = re.sub(r"[^\w\-. ]+", "_", (value or "").strip())
    safe = re.sub(r"\s+", "-", safe)
    safe = safe.strip(".-_")
    return safe or "timeline"


def default_timelines_dir() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "project" / "timelines"


def compute_name_options(name: str) -> tuple[str, str]:
    raw = sanitize_filename(name)
    leading = LEADING_NUM_RE.match(raw)
    if leading:
        cur_num = int(leading.group("num"))
        width = len(leading.group("num"))
        return raw, f"{cur_num + 1:0{width}d}"

    match = VERSION_TOKEN_RE.match(raw)
    if not match:
        return raw, f"{raw}_v001"

    prefix = (match.group("prefix") or "").rstrip(" _-")
    sep = match.group("sep") or "_"
    num_s = match.group("num") or "0"
    width = max(3, len(num_s))
    cur_num = int(num_s)
    next_num = cur_num + 1
    current = f"{prefix}{sep}v{cur_num:0{width}d}"
    nxt = f"{prefix}{sep}v{next_num:0{width}d}"
    return sanitize_filename(current), sanitize_filename(nxt)


def compute_name_options_from_existing(
    timeline_name: str, output_dir: Path
) -> tuple[str, str]:
    raw = sanitize_filename(timeline_name)
    m = NUM_SUFFIX_RE.match(raw)
    if not m:
        return compute_name_options(raw)

    seed_num = m.group("num")
    suffix = m.group("suffix") or ""
    width = len(seed_num)
    major_prefix = seed_num[:2] if len(seed_num) >= 2 else seed_num

    candidates = []
    for p in output_dir.glob("*.drt"):
        stem = sanitize_filename(p.stem)
        mm = NUM_SUFFIX_RE.match(stem)
        if not mm:
            continue
        num_s = mm.group("num")
        suf = mm.group("suffix") or ""
        if suf != suffix:
            continue
        if major_prefix and not num_s.startswith(major_prefix):
            continue
        candidates.append((int(num_s), len(num_s), stem))

    if not candidates:
        return raw, f"{int(seed_num) + 1:0{width}d}{suffix}"

    latest_num, latest_width, latest_name = sorted(candidates, key=lambda x: x[0])[-1]
    next_name = f"{latest_num + 1:0{latest_width}d}{suffix}"
    return latest_name, next_name


def choose_output_name(args, timeline_name: str, output_dir: Path) -> str:
    current_name, next_name = compute_name_options_from_existing(timeline_name, output_dir)
    allowed = {current_name, next_name}

    if args.output_name:
        chosen = sanitize_filename(args.output_name)
        if chosen in allowed or args.force:
            return chosen
        raise RuntimeError(
            f"--output-name must be one of: '{current_name}' or '{next_name}' (or use --force)."
        )

    print("\n--- Export Name ---")
    print(f"1) {current_name} (current)")
    print(f"2) {next_name} (next)")
    while True:
        reply = input("Choose export name [1/2] (Enter=2): ").strip()
        if reply == "" or reply == "2":
            return next_name
        if reply == "1":
            return current_name
        print("Invalid selection. Enter 1 or 2.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Export currently open timeline to project/timelines as a .drt file."
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_timelines_dir()),
        help="Target folder for exported .drt files (default: %(default)s).",
    )
    parser.add_argument(
        "--output-name",
        default="",
        help="Export file name override. Must be current or next version unless --force.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .drt if it already exists.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all project timelines to .drt files.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.name.lower() != "timelines":
        raise RuntimeError(f"Output folder must be named 'timelines': {output_dir}")
    if not output_dir.exists():
        raise RuntimeError(
            f"Required folder missing: {output_dir}\n"
            "Make sure that you have the latest project (.drp)."
        )

    resolve_module = load_resolve_script_module()
    resolve = resolve_module.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve.")

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        raise RuntimeError("No current Resolve project is open.")

    print("=== Export Timeline ===")
    print(f"Project      : {project.GetName()}")
    print(f"Output dir   : {output_dir}")
    print(f"Export all   : {'yes' if args.all else 'no'}")
    print("=======================")

    if args.all:
        count = project.GetTimelineCount() or 0
        exported = 0
        failed = 0
        for i in range(1, count + 1):
            timeline = project.GetTimelineByIndex(i)
            if not timeline:
                failed += 1
                continue
            timeline_name = timeline.GetName() or f"timeline-{i}"
            output_name = sanitize_filename(timeline_name)
            output_path = output_dir / f"{output_name}.drt"
            if output_path.exists() and not args.force:
                failed += 1
                print(f"Skipped (exists): {output_path.name}")
                continue
            ok = bool(timeline.Export(str(output_path), DRT_EXPORT_TYPE))
            if ok and output_path.exists():
                exported += 1
                print(f"Exported: {timeline_name} -> {output_path.name}")
            else:
                failed += 1
                print(f"Failed: {timeline_name}")
        print(f"Summary: exported={exported}, failed={failed}")
        if failed:
            raise RuntimeError("One or more timeline exports failed.")
        return

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No current/open timeline found.")

    timeline_name = timeline.GetName() or "timeline"
    output_name = choose_output_name(args, timeline_name, output_dir)
    output_path = output_dir / f"{output_name}.drt"
    if output_path.exists() and not args.force:
        raise RuntimeError(
            f"Output file already exists: {output_path}\n"
            "Re-run with --force to overwrite."
        )

    print(f"Timeline     : {timeline_name}")
    print(f"Output path  : {output_path}")
    ok = bool(timeline.Export(str(output_path), DRT_EXPORT_TYPE))
    if not ok or not output_path.exists():
        raise RuntimeError("Timeline export failed.")

    print(f"Export result: success ({output_path})")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
