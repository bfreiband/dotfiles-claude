#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Reconcile out-of-band edits from live targets back into the repo.

Walks each managed target, computes the expected content (repo + .local
overlay), diffs it against the live file, and for each change prompts
whether to route it into the repo file, the .local overlay, or discard.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from difflib import unified_diff
from pathlib import Path
from typing import Iterator, Literal


# ---------------------------------------------------------------------------
# 1. Constants (mirrored from install.py)
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent
HOME = Path.home()
DEST = HOME / ".claude"
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))

SKIP_NAMES = {".DS_Store", "__pycache__", ".git"}

OVERLAY_TARGETS: list[tuple[Path, Path, str]] = [
    (REPO / "settings.json", DEST / "settings.json", "claude-settings"),
    (REPO / "xdg" / ".config" / "ccstatusline" / "settings.json",
     XDG_CONFIG / "ccstatusline" / "settings.json", "generic"),
]


# ---------------------------------------------------------------------------
# 2. Helpers (subset from install.py)
# ---------------------------------------------------------------------------

def _rel(p: Path) -> str:
    try:
        return "~/" + str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def local_path_for(base: Path) -> Path:
    return base.with_suffix(".local.json")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def normalize_hook_command(cmd: str) -> str:
    s = cmd.replace(str(HOME), "$HOME")
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_hook_block(block: dict) -> str:
    hooks = block.get("hooks", [])
    cmds = [normalize_hook_command(h.get("command", "")) for h in hooks]
    return f"{block.get('matcher', '')}|{'|'.join(cmds)}"


def merge_hook_array(existing: list, repo: list, mode: str) -> list:
    if mode == "keep-existing":
        return existing
    if mode == "take-repo":
        return repo
    seen: dict[str, dict] = {}
    for block in [*existing, *repo]:
        sig = _normalize_hook_block(block)
        if sig not in seen:
            seen[sig] = block
    return list(seen.values())


def overlay_json(base: dict, overlay: dict, profile: str) -> dict:
    out = dict(base)
    for key in overlay:
        if key not in base:
            out[key] = overlay[key]
            continue
        bv, ov = base[key], overlay[key]
        if isinstance(bv, dict) and isinstance(ov, dict):
            if profile == "claude-settings" and key == "hooks":
                out[key] = _overlay_hooks(bv, ov)
            else:
                out[key] = overlay_json(bv, ov, profile)
        else:
            out[key] = ov
    return out


def _overlay_hooks(base_hooks: dict, overlay_hooks: dict) -> dict:
    out = dict(base_hooks)
    for event in overlay_hooks:
        if event not in base_hooks:
            out[event] = overlay_hooks[event]
        else:
            out[event] = merge_hook_array(base_hooks[event], overlay_hooks[event], "union")
    return out


def load_overlayed(base: Path, profile: str) -> dict:
    base_dict = _load_json(base) or {}
    local = _load_json(local_path_for(base))
    if local is None:
        return base_dict
    return overlay_json(base_dict, local, profile)


def serialize_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _walk_tracked(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for f in filenames:
            if f in SKIP_NAMES or f.endswith(".local.json"):
                continue
            yield Path(dirpath) / f


# ---------------------------------------------------------------------------
# 3. JSON diff engine
# ---------------------------------------------------------------------------

Change = tuple[str, Literal["added", "removed", "modified"], object, object]


def json_diff(expected: dict, live: dict, prefix: str = "") -> list[Change]:
    changes: list[Change] = []
    all_keys = sorted(set(expected) | set(live))
    for k in all_keys:
        path = f"{prefix}.{k}" if prefix else k
        in_exp = k in expected
        in_live = k in live
        if in_exp and not in_live:
            changes.append((path, "removed", expected[k], None))
        elif in_live and not in_exp:
            changes.append((path, "added", None, live[k]))
        elif isinstance(expected[k], dict) and isinstance(live[k], dict):
            changes.extend(json_diff(expected[k], live[k], path))
        elif expected[k] != live[k]:
            changes.append((path, "modified", expected[k], live[k]))
    return changes


def _is_local_owned(dotpath: str, local_dict: dict) -> bool:
    """A key is local-owned if any prefix of its path exists in the local overlay."""
    parts = dotpath.split(".")
    d = local_dict
    for part in parts:
        if not isinstance(d, dict):
            return False
        if part in d:
            d = d[part]
        else:
            return False
    return True


def _set_at_path(d: dict, dotpath: str, value: object) -> None:
    parts = dotpath.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _del_at_path(d: dict, dotpath: str) -> None:
    parts = dotpath.split(".")
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            return
        d = d[part]
    d.pop(parts[-1], None)


def _clean_empty_dicts(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            cleaned = _clean_empty_dicts(v)
            if cleaned:
                out[k] = cleaned
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# 4. Prompts
# ---------------------------------------------------------------------------

def _ask(prompt: str, choices: dict[str, str], default: str) -> str:
    opts = "/".join(f"[{k}]{v}" if k == default else f"{k}={v}" for k, v in choices.items())
    while True:
        raw = input(f"{prompt}\n  {opts}\n> ").strip().lower()
        if raw == "":
            return default
        if raw in choices:
            return raw
        print(f"  (unrecognized: {raw!r})")


def prompt_json_change(change: Change) -> str:
    path, kind, expected_val, live_val = change
    print(f"\n  Path: {path}")
    if kind == "added":
        print(f"  expected: (absent)")
        print(f"  live:     {json.dumps(live_val)[:200]}")
    elif kind == "removed":
        print(f"  expected: {json.dumps(expected_val)[:200]}")
        print(f"  live:     (absent)")
    else:
        print(f"  expected: {json.dumps(expected_val)[:200]}")
        print(f"  live:     {json.dumps(live_val)[:200]}")

    choice = _ask(
        "Route this change?",
        {"r": "repo", "l": "local (.local.json)", "d": "discard (revert on next install)", "s": "skip"},
        default="s",
    )
    return {"r": "repo", "l": "local", "d": "discard", "s": "skip"}[choice]


def prompt_file_change(repo_src: Path, dst: Path) -> str:
    print(f"\n  File: {_rel(dst)}")
    print(f"  Repo: {_rel(repo_src)}")
    while True:
        choice = _ask(
            "Route this change?",
            {"r": "repo (overwrite repo file)", "d": "discard (revert on next install)",
             "v": "view diff", "s": "skip"},
            default="s",
        )
        if choice == "v":
            _print_file_diff(repo_src, dst)
            continue
        return {"r": "repo", "d": "discard", "s": "skip"}[choice]


def _print_file_diff(a: Path, b: Path) -> None:
    try:
        a_lines = a.read_text().splitlines(keepends=True)
        b_lines = b.read_text().splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as e:
        print(f"  (cannot diff: {e})")
        return
    for line in unified_diff(a_lines, b_lines, fromfile=str(a), tofile=str(b), n=3):
        sys.stdout.write(line)
    print()


# ---------------------------------------------------------------------------
# 5. Writers
# ---------------------------------------------------------------------------

def write_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(serialize_json(data))
    os.replace(tmp, path)
    print(f"  wrote {_rel(path)}")


# ---------------------------------------------------------------------------
# 6. Reconcile logic
# ---------------------------------------------------------------------------

def reconcile_json_target(repo_src: Path, dst: Path, profile: str,
                          dry_run: bool) -> None:
    repo_dict = _load_json(repo_src)
    if repo_dict is None:
        print(f"  skip (cannot read repo): {_rel(repo_src)}")
        return
    local_dict = _load_json(local_path_for(repo_src)) or {}
    live_dict = _load_json(dst)
    if live_dict is None:
        print(f"  skip (cannot read live): {_rel(dst)}")
        return

    expected = overlay_json(repo_dict, local_dict, profile)
    if expected == live_dict:
        print(f"[=] {_rel(dst)} — in sync")
        return

    changes = json_diff(expected, live_dict)
    if not changes:
        print(f"[=] {_rel(dst)} — in sync")
        return

    print(f"[!] {_rel(dst)} — {len(changes)} difference(s)")

    repo_changed = False
    local_changed = False

    for change in changes:
        path, kind, expected_val, live_val = change
        if dry_run:
            auto = " (local-owned)" if _is_local_owned(path, local_dict) else ""
            print(f"  {kind}: {path}{auto}")
            continue

        if _is_local_owned(path, local_dict):
            decision = "local"
            if kind == "removed":
                print(f"  auto-route {path} -> local (remove)")
            else:
                print(f"  auto-route {path} -> local")
        else:
            decision = prompt_json_change(change)

        if decision == "skip" or decision == "discard":
            continue

        target_dict = repo_dict if decision == "repo" else local_dict
        if kind == "removed":
            _del_at_path(target_dict, path)
        else:
            _set_at_path(target_dict, path, live_val)

        if decision == "repo":
            repo_changed = True
        else:
            local_changed = True

    if dry_run:
        return

    if repo_changed:
        write_json_file(repo_src, repo_dict)
    if local_changed:
        cleaned = _clean_empty_dicts(local_dict)
        if cleaned:
            write_json_file(local_path_for(repo_src), cleaned)
        else:
            lp = local_path_for(repo_src)
            if lp.exists():
                lp.unlink()
                print(f"  removed empty {_rel(lp)}")


def reconcile_file_target(repo_src: Path, dst: Path, dry_run: bool) -> None:
    if not dst.is_file():
        return
    if dst.is_symlink():
        return

    try:
        repo_content = repo_src.read_bytes()
        live_content = dst.read_bytes()
    except OSError:
        return

    if repo_content == live_content:
        print(f"[=] {_rel(dst)} — in sync")
        return

    print(f"[!] {_rel(dst)} — differs from repo")

    if dry_run:
        return

    decision = prompt_file_change(repo_src, dst)
    if decision == "repo":
        import shutil
        shutil.copy2(dst, repo_src)
        print(f"  copied live -> {_rel(repo_src)}")
    elif decision in ("discard", "skip"):
        pass


def reconcile_skills(dry_run: bool) -> None:
    skills_dir = REPO / "skills"
    if not skills_dir.is_dir():
        return
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_NAMES:
            continue
        dst_root = DEST / "skills" / entry.name
        if not dst_root.is_dir():
            continue
        for src_file in sorted(_walk_tracked(entry)):
            rel = src_file.relative_to(entry)
            dst_file = dst_root / rel
            reconcile_file_target(src_file, dst_file, dry_run)


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="show diffs only; no writes")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print("Reconciling live targets against repo + local overlays...\n")

    for repo_src, dst, profile in OVERLAY_TARGETS:
        if not repo_src.exists():
            continue
        reconcile_json_target(repo_src, dst, profile, args.dry_run)

    # Non-JSON file targets
    hooks_dir = REPO / "hooks"
    if hooks_dir.is_dir():
        for entry in sorted(hooks_dir.iterdir()):
            if entry.name.startswith(".") or entry.name.endswith(".example"):
                continue
            if entry.is_file() and not entry.name.endswith(".local.json"):
                dst = DEST / "hooks" / entry.name
                reconcile_file_target(entry, dst, args.dry_run)

    reconcile_skills(args.dry_run)

    # XDG non-JSON files
    xdg_src = REPO / "xdg" / ".config"
    if xdg_src.is_dir():
        already_overlayed = {
            (rs.parent, rs.name) for rs, _, _ in OVERLAY_TARGETS
        }
        for tool_dir in sorted(xdg_src.iterdir()):
            if not tool_dir.is_dir() or tool_dir.name in SKIP_NAMES:
                continue
            for src_file in sorted(_walk_tracked(tool_dir)):
                if (src_file.parent, src_file.name) in already_overlayed:
                    continue
                dst_file = XDG_CONFIG / tool_dir.name / src_file.relative_to(tool_dir)
                reconcile_file_target(src_file, dst_file, args.dry_run)

    print("\nDone. Run ./install.py to sync any accepted changes to live targets.")


if __name__ == "__main__":
    main()
