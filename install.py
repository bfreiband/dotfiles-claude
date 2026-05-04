#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Copy-based installer for dotfiles-claude with .local.json overlays.

Walks the repo, merges each JSON target with its optional .local.json
overlay, classifies every destination, prints a plan, then (unless
--dry-run) writes regular files. Designed to be safely re-runnable:
identical targets are no-ops, drifted targets get prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from difflib import unified_diff
from pathlib import Path
from typing import Iterator, Literal


# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent
HOME = Path.home()
DEST = HOME / ".claude"
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")))
BACKUP_ROOT = HOME / ".dotfiles-claude-backups"

SECTIONS = ("settings", "hooks", "skills", "skills-upstream", "xdg")

SKIP_NAMES = {".DS_Store", "__pycache__", ".git"}

SYMBOL = {
    "new":       "[+] ",
    "identical": "[=] ",
    "drift":     "[!] ",
    "orphan":    "[?] ",
}

LEGEND = {
    "new":       "target missing; will copy",
    "identical": "target matches expected content; no action needed",
    "drift":     "target differs from expected; will prompt",
    "orphan":    "file in destination not in repo; will prompt",
}

OVERLAY_TARGETS: list[tuple[Path, Path, str]] = [
    (REPO / "settings.json", DEST / "settings.json", "claude-settings"),
    (REPO / "xdg" / ".config" / "ccstatusline" / "settings.json",
     XDG_CONFIG / "ccstatusline" / "settings.json", "generic"),
]


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="print plan only; no writes")
    p.add_argument("--yes", "-y", action="store_true",
                   help="non-interactive: safe default for every prompt")
    p.add_argument("--only", action="append", choices=SECTIONS, default=None,
                   help="restrict to named section (repeatable)")
    p.add_argument("--verbose", "-v", action="store_true", help="per-file detail for directories")
    return p.parse_args()


def section_enabled(section: str, only: list[str] | None) -> bool:
    return only is None or section in only


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileCopyAction:
    src: Path
    dst: Path
    status: Literal["new", "identical", "drift"]
    content: bytes
    detail: str = ""
    mode: int | None = None


@dataclass
class SkillDirAction:
    name: str
    src_root: Path
    dst_root: Path
    file_actions: list[FileCopyAction] = field(default_factory=list)
    orphans: list[Path] = field(default_factory=list)


@dataclass
class UpstreamSkillAction:
    name: str
    upstream: str
    status: Literal["new", "identical"]
    dst: Path


Action = FileCopyAction | SkillDirAction | UpstreamSkillAction


# ---------------------------------------------------------------------------
# Overlay engine
# ---------------------------------------------------------------------------

def local_path_for(base: Path) -> Path:
    return base.with_suffix(".local.json")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


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
            out[event] = _merge_hook_array(base_hooks[event], overlay_hooks[event])
    return out


def _normalize_hook_command(cmd: str) -> str:
    s = cmd.replace(str(HOME), "$HOME")
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_hook_block(block: dict) -> str:
    hooks = block.get("hooks", [])
    cmds = [_normalize_hook_command(h.get("command", "")) for h in hooks]
    return f"{block.get('matcher', '')}|{'|'.join(cmds)}"


def _merge_hook_array(existing: list, incoming: list) -> list:
    seen: dict[str, dict] = {}
    for block in [*existing, *incoming]:
        sig = _normalize_hook_block(block)
        if sig not in seen:
            seen[sig] = block
    return list(seen.values())


def load_overlayed(base: Path, profile: str) -> tuple[dict, bool]:
    """Returns (merged_dict, was_overlayed)."""
    base_dict = _load_json(base) or {}
    local = _load_json(local_path_for(base))
    if local is None:
        return base_dict, False
    return overlay_json(base_dict, local, profile), True


def serialize_json(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _symlink_points_into_repo(path: Path) -> bool:
    if not path.is_symlink():
        return False
    try:
        target = path.resolve()
        return str(target).startswith(str(REPO) + "/") or target == REPO
    except OSError:
        return False


def classify_file(src: Path, dst: Path, content: bytes,
                  mode: int | None = None) -> FileCopyAction:
    if not dst.exists() and not dst.is_symlink():
        return FileCopyAction(src, dst, "new", content, mode=mode)

    if _symlink_points_into_repo(dst):
        try:
            existing = dst.resolve().read_bytes()
        except OSError:
            existing = b""
        if existing == content:
            return FileCopyAction(src, dst, "identical", content,
                                  detail="symlink -> copy (content matches)", mode=mode)
        return FileCopyAction(src, dst, "drift", content,
                              detail="symlink -> copy (content differs)", mode=mode)

    if dst.is_symlink():
        return FileCopyAction(src, dst, "drift", content,
                              detail=f"symlink -> {os.readlink(dst)}", mode=mode)

    if dst.is_file():
        try:
            if dst.read_bytes() == content:
                return FileCopyAction(src, dst, "identical", content, mode=mode)
        except OSError:
            pass
        return FileCopyAction(src, dst, "drift", content, detail="file contents differ",
                              mode=mode)

    return FileCopyAction(src, dst, "drift", content, detail="type mismatch", mode=mode)


def _walk_tracked(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for f in filenames:
            if f in SKIP_NAMES or f.endswith(".local.json"):
                continue
            yield Path(dirpath) / f


def parse_upstream_skills(skills_md: Path) -> list[tuple[str, str]]:
    """Parses the `| Skill | Upstream |` table in skills.md.

    Returns [(name, upstream_url), ...]. The `(path: ...)` annotation in the
    Upstream column is human-readable only; `npx skills add` discovers the
    SKILL.md location itself.
    """
    if not skills_md.is_file():
        return []
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in skills_md.read_text().splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0].lower() == "skill" and cells[1].lower() == "upstream":
            in_table = True
            continue
        if not in_table:
            continue
        if set(cells[0]) <= {"-", ":", " "}:
            continue
        name = cells[0].strip("`")
        upstream_cell = cells[1]
        m = re.search(r"https?://\S+", upstream_cell)
        if not m:
            continue
        url = m.group(0).rstrip(")")
        rows.append((name, url))
    return rows


def classify_skill(name: str) -> SkillDirAction:
    src_root = REPO / "skills" / name
    dst_root = DEST / "skills" / name
    action = SkillDirAction(name=name, src_root=src_root, dst_root=dst_root)

    for src_file in sorted(_walk_tracked(src_root)):
        rel = src_file.relative_to(src_root)
        dst_file = dst_root / rel
        content = src_file.read_bytes()
        mode = src_file.stat().st_mode & 0o777
        action.file_actions.append(classify_file(src_file, dst_file, content, mode=mode))

    if dst_root.is_dir() or (dst_root.is_symlink() and dst_root.resolve().is_dir()):
        actual_root = dst_root.resolve() if dst_root.is_symlink() else dst_root
        repo_rels = {f.relative_to(src_root) for f in _walk_tracked(src_root)}
        for dst_file in sorted(_walk_tracked(actual_root)):
            try:
                rel = dst_file.relative_to(actual_root)
            except ValueError:
                continue
            if rel not in repo_rels:
                action.orphans.append(dst_file)

    return action


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def build_plan(args: argparse.Namespace) -> list[Action]:
    plan: list[Action] = []

    for repo_src, dst, profile in OVERLAY_TARGETS:
        section = "settings" if repo_src.name == "settings.json" and repo_src.parent == REPO else "xdg"
        if not section_enabled(section, args.only):
            continue
        if not repo_src.exists():
            continue
        merged, was_overlayed = load_overlayed(repo_src, profile)
        if was_overlayed:
            content = serialize_json(merged)
        else:
            content = repo_src.read_bytes()
        plan.append(classify_file(repo_src, dst, content))

    if section_enabled("hooks", args.only):
        hooks_dir = REPO / "hooks"
        if hooks_dir.is_dir():
            for entry in sorted(hooks_dir.iterdir()):
                if entry.name.startswith(".") or entry.name.endswith(".example"):
                    continue
                if entry.is_file() and not entry.name.endswith(".local.json"):
                    dst = DEST / "hooks" / entry.name
                    content = entry.read_bytes()
                    mode = entry.stat().st_mode & 0o777
                    plan.append(classify_file(entry, dst, content, mode=mode))

    if section_enabled("skills", args.only):
        skills_dir = REPO / "skills"
        if skills_dir.is_dir():
            for entry in sorted(skills_dir.iterdir()):
                if entry.is_dir() and entry.name not in SKIP_NAMES:
                    plan.append(classify_skill(entry.name))

    if section_enabled("skills-upstream", args.only):
        for skill in parse_upstream_skills(REPO / "skills.md"):
            name, upstream = skill
            dst = DEST / "skills" / name
            status = "identical" if (dst.exists() or dst.is_symlink()) else "new"
            plan.append(UpstreamSkillAction(name=name, upstream=upstream,
                                            status=status, dst=dst))

    if section_enabled("xdg", args.only):
        xdg_src = REPO / "xdg" / ".config"
        if xdg_src.is_dir():
            already_overlayed = {
                (repo_src.parent, repo_src.name)
                for repo_src, _, _ in OVERLAY_TARGETS
            }
            for tool_dir in sorted(xdg_src.iterdir()):
                if not tool_dir.is_dir() or tool_dir.name in SKIP_NAMES:
                    continue
                for src_file in sorted(_walk_tracked(tool_dir)):
                    if (src_file.parent, src_file.name) in already_overlayed:
                        continue
                    dst_file = XDG_CONFIG / tool_dir.name / src_file.relative_to(tool_dir)
                    content = src_file.read_bytes()
                    mode = src_file.stat().st_mode & 0o777
                    plan.append(classify_file(src_file, dst_file, content, mode=mode))

    return plan


# ---------------------------------------------------------------------------
# Plan printing
# ---------------------------------------------------------------------------

def _rel(p: Path) -> str:
    try:
        return "~/" + str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def _status_of(a: Action) -> str:
    if isinstance(a, FileCopyAction):
        return a.status
    if isinstance(a, SkillDirAction):
        statuses = [fa.status for fa in a.file_actions]
        if a.orphans:
            return "orphan"
        if any(s == "drift" for s in statuses):
            return "drift"
        if any(s == "new" for s in statuses):
            return "new"
        return "identical"
    if isinstance(a, UpstreamSkillAction):
        return a.status
    return "identical"


def _print_legend(statuses: set[str]) -> None:
    if not statuses:
        return
    print("Key:")
    for status in ("new", "identical", "drift", "orphan"):
        if status in statuses:
            print(f"  {SYMBOL[status]} {status:<16} {LEGEND[status]}")
    print()


def _summarize_skill(action: SkillDirAction) -> str:
    counts: dict[str, int] = {"new": 0, "identical": 0, "drift": 0}
    for fa in action.file_actions:
        counts[fa.status] = counts.get(fa.status, 0) + 1
    total = sum(counts.values())
    parts = [f"{total} file{'s' if total != 1 else ''}"]
    for s in ("identical", "new", "drift"):
        if counts[s]:
            parts.append(f"{counts[s]} {s}")
    if action.orphans:
        parts.append(f"{len(action.orphans)} orphan")
    return ", ".join(parts)


def print_plan(plan: list[Action], verbose: bool = False) -> None:
    statuses = {_status_of(a) for a in plan}
    _print_legend(statuses)
    print("Plan:")
    if not plan:
        print("  (nothing to do)")
        print()
        return
    for action in plan:
        status = _status_of(action)
        symbol = SYMBOL.get(status, "    ")
        if isinstance(action, FileCopyAction):
            line = f"  {symbol} {_rel(action.dst)}"
            if action.detail:
                line += f"  ({action.detail})"
            print(line)
        elif isinstance(action, SkillDirAction):
            print(f"  {symbol} skills/{action.name}  ({_summarize_skill(action)})")
            if verbose:
                for fa in action.file_actions:
                    fa_sym = SYMBOL.get(fa.status, "    ")
                    rel = fa.dst.relative_to(action.dst_root)
                    print(f"    {fa_sym} {rel}")
                for orph in action.orphans:
                    rel = orph.relative_to(action.dst_root) if str(orph).startswith(str(action.dst_root)) else orph
                    print(f"    {SYMBOL['orphan']} {rel}  (not in repo)")
        elif isinstance(action, UpstreamSkillAction):
            if action.status == "identical":
                detail = "already installed"
            else:
                detail = ("will run: npx skills add "
                          f"{action.upstream} --skill {action.name} "
                          "-g --agent claude-code -y")
            print(f"  {symbol} skills/{action.name}  ({detail})")
    print()


# ---------------------------------------------------------------------------
# Prompts
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


def prompt_drift(action: FileCopyAction) -> str:
    print(f"\nDrift: {_rel(action.dst)}  ({action.detail})")
    while True:
        choice = _ask(
            "Action?",
            {"t": "take-expected (backup + write)", "k": "keep existing", "d": "diff", "a": "abort"},
            default="t",
        )
        if choice == "d":
            _print_file_diff(action.dst, action.content)
            continue
        return {"t": "take-expected", "k": "keep", "a": "abort"}[choice]


def _print_file_diff(existing_path: Path, expected_content: bytes) -> None:
    try:
        a = existing_path.read_text().splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as e:
        print(f"  (cannot read existing: {e})")
        return
    try:
        b = expected_content.decode().splitlines(keepends=True)
    except UnicodeDecodeError:
        print("  (binary content; cannot diff)")
        return
    for line in unified_diff(a, b, fromfile=str(existing_path), tofile="(expected)", n=3):
        sys.stdout.write(line)
    print()


def prompt_orphan_policy(skill: SkillDirAction) -> str:
    print(f"\nSkill {skill.name!r}: {len(skill.orphans)} file(s) in destination not in repo:")
    for o in skill.orphans[:10]:
        try:
            rel = o.relative_to(skill.dst_root)
        except ValueError:
            rel = o
        print(f"  {rel}")
    if len(skill.orphans) > 10:
        print(f"  ... and {len(skill.orphans) - 10} more")
    choice = _ask(
        "Action?",
        {"k": "keep-all", "d": "delete-all", "s": "skip"},
        default="k",
    )
    return {"k": "keep-all", "d": "delete-all", "s": "skip"}[choice]


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def ensure_dirs(dry_run: bool) -> None:
    if dry_run:
        return
    for d in (DEST / "hooks", DEST / "skills", XDG_CONFIG, BACKUP_ROOT):
        d.mkdir(parents=True, exist_ok=True)


def backup(path: Path, dry_run: bool) -> Path:
    rel = path.relative_to(HOME) if str(path).startswith(str(HOME) + "/") else Path(str(path).lstrip("/"))
    target = BACKUP_ROOT / rel
    if target.exists() or target.is_symlink():
        target = target.with_name(f"{target.name}.{datetime.now():%Y%m%d-%H%M%S}")
    if dry_run:
        print(f"  would back up {_rel(path)} -> {_rel(target)}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        link_target = os.readlink(path)
        os.symlink(link_target, target)
        path.unlink()
    else:
        shutil.move(str(path), str(target))
    print(f"  backed up {_rel(path)} -> {_rel(target)}")
    return target


def _ensure_real_parent(dst: Path) -> None:
    """If any ancestor of dst is a symlink into the repo, replace it with a real directory."""
    p = dst.parent
    while p != p.parent:
        if p.is_symlink() and _symlink_points_into_repo(p):
            resolved = p.resolve()
            p.unlink()
            shutil.copytree(resolved, p)
            print(f"  replaced dir symlink with copy: {_rel(p)}")
            return
        p = p.parent


def copy_file(content: bytes, dst: Path, dry_run: bool, mode: int | None = None) -> None:
    if dry_run:
        print(f"  would write {_rel(dst)} ({len(content)} bytes)")
        return
    _ensure_real_parent(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_bytes(content)
    if mode is not None:
        tmp.chmod(mode)
    os.replace(tmp, dst)
    print(f"  wrote {_rel(dst)}")


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def execute_file_copy(action: FileCopyAction, args: argparse.Namespace) -> None:
    if action.status == "identical":
        if args.verbose:
            print(f"  skip (identical): {_rel(action.dst)}")
        if action.dst.is_symlink():
            _replace_symlink_with_file(action, args)
        return
    if action.status == "new":
        copy_file(action.content, action.dst, args.dry_run, mode=action.mode)
        return
    decision = "take-expected" if args.yes else prompt_drift(action)
    if decision == "abort":
        print("Aborted.")
        sys.exit(1)
    if decision == "keep":
        print(f"  keeping existing {_rel(action.dst)}")
        return
    backup(action.dst, args.dry_run)
    copy_file(action.content, action.dst, args.dry_run, mode=action.mode)


def _replace_symlink_with_file(action: FileCopyAction, args: argparse.Namespace) -> None:
    if args.dry_run:
        print(f"  would replace symlink with file: {_rel(action.dst)}")
        return
    action.dst.unlink()
    copy_file(action.content, action.dst, False, mode=action.mode)


def execute_skill_dir(action: SkillDirAction, args: argparse.Namespace) -> None:
    if action.dst_root.is_symlink() and _symlink_points_into_repo(action.dst_root):
        if not args.dry_run:
            action.dst_root.unlink()
            print(f"  removed skill symlink: {_rel(action.dst_root)}")

    for fa in action.file_actions:
        execute_file_copy(fa, args)

    if action.orphans:
        policy = "keep-all" if args.yes or args.dry_run else prompt_orphan_policy(action)
        if policy == "delete-all":
            for orph in action.orphans:
                if args.dry_run:
                    print(f"  would delete orphan: {_rel(orph)}")
                else:
                    orph.unlink()
                    print(f"  deleted orphan: {_rel(orph)}")


def execute_upstream_skill(action: UpstreamSkillAction, args: argparse.Namespace) -> None:
    if action.status == "identical":
        if args.verbose:
            print(f"  skip (already installed): {_rel(action.dst)}")
        return
    cmd = ["npx", "--yes", "skills", "add", action.upstream,
           "--skill", action.name, "-g", "--agent", "claude-code", "-y"]
    if args.dry_run:
        print(f"  would run: {' '.join(cmd)}")
        return
    print(f"  running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  npx skills add failed for {action.name} (exit {result.returncode})")
        sys.exit(1)


def require_npx(plan: list[Action]) -> None:
    needs_npx = any(
        isinstance(a, UpstreamSkillAction) and a.status == "new" for a in plan
    )
    if not needs_npx:
        return
    if shutil.which("npx") is None:
        print("error: npx is required to install upstream skills but was not found on PATH.")
        print("       install Node.js (npm ships with npx) and re-run, or pass --only to skip.")
        sys.exit(1)


def execute(plan: list[Action], args: argparse.Namespace) -> None:
    for action in plan:
        if isinstance(action, FileCopyAction):
            execute_file_copy(action, args)
        elif isinstance(action, SkillDirAction):
            execute_skill_dir(action, args)
        elif isinstance(action, UpstreamSkillAction):
            execute_upstream_skill(action, args)


# ---------------------------------------------------------------------------
# Bootstrap: seed .local.json from existing system file
# ---------------------------------------------------------------------------

def _diff_keys(base: dict, live: dict, prefix: str = "") -> dict:
    """Returns keys/values in live that differ from or are absent in base."""
    diff: dict = {}
    for k, v in live.items():
        path = f"{prefix}.{k}" if prefix else k
        if k not in base:
            diff[k] = v
        elif isinstance(base[k], dict) and isinstance(v, dict):
            sub = _diff_keys(base[k], v, path)
            if sub:
                diff[k] = sub
        elif base[k] != v:
            diff[k] = v
    return diff


def bootstrap_local(repo_src: Path, dst: Path, profile: str, args: argparse.Namespace) -> None:
    """If no .local.json exists but the system file does, offer to seed one from the diff."""
    local_file = local_path_for(repo_src)
    if local_file.exists():
        return
    if not dst.is_file() or dst.is_symlink():
        return

    repo_dict = _load_json(repo_src) or {}
    live_dict = _load_json(dst)
    if live_dict is None:
        return

    diff = _diff_keys(repo_dict, live_dict)
    if not diff:
        return

    print(f"\nFound existing {_rel(dst)} with {_count_leaves(diff)} key(s) not in the repo:")
    for path, val in _flat_leaves(diff):
        print(f"  {path}: {json.dumps(val, ensure_ascii=False)[:100]}")

    if args.yes:
        accept = True
    elif args.dry_run:
        print(f"  would create {_rel(local_file)} with these keys")
        return
    else:
        choice = _ask(
            f"\nSeed {_rel(local_file)} with these machine-specific keys?",
            {"y": "yes", "n": "no"},
            default="y",
        )
        accept = choice == "y"

    if not accept:
        return

    local_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_file.with_name(local_file.name + ".tmp")
    tmp.write_bytes(serialize_json(diff))
    os.replace(tmp, local_file)
    print(f"  created {_rel(local_file)}")


def _count_leaves(d: dict) -> int:
    count = 0
    for v in d.values():
        if isinstance(v, dict):
            count += _count_leaves(v)
        else:
            count += 1
    return count


def _flat_leaves(d: dict, prefix: str = "") -> list[tuple[str, object]]:
    out = []
    for k, v in sorted(d.items()):
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_flat_leaves(v, path))
        else:
            out.append((path, v))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    ensure_dirs(args.dry_run)

    # Offer to bootstrap .local.json from existing system files
    for repo_src, dst, profile in OVERLAY_TARGETS:
        bootstrap_local(repo_src, dst, profile, args)

    plan = build_plan(args)
    print_plan(plan, verbose=args.verbose)

    if args.dry_run:
        print("Dry run: no changes made.")
        return
    if not plan:
        print("Nothing to do.")
        return

    require_npx(plan)
    execute(plan, args)
    print("\nDone. Restart Claude Code to pick up settings changes.")


if __name__ == "__main__":
    main()
