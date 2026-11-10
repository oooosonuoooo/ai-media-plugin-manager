#!/usr/bin/env python3
"""Install the command and link this skill into user-level IDE skill folders."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


SKILL_NAME = "ai-media-plugin-manager"
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_SOURCE = REPO_ROOT / "scripts" / "media-assets"


def skill_targets() -> dict[str, Path]:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    # Current Antigravity IDE documentation uses this global skill directory.
    antigravity_root = home / ".gemini/config/skills"
    return {
        "codex": codex_home / "skills" / SKILL_NAME,
        "antigravity": antigravity_root / SKILL_NAME,
    }


def install_targets() -> dict[str, tuple[Path, Path, bool]]:
    home = Path.home()
    skills = skill_targets()
    return {
        "codex": (skills["codex"], REPO_ROOT, True),
        "antigravity": (skills["antigravity"], REPO_ROOT, True),
        "cli": (home / ".local/bin/media-assets", CLI_SOURCE, False),
    }


def install_link(target: Path, source: Path, *, target_is_directory: bool, repair: bool = False) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        try:
            resolved = target.resolve(strict=True)
        except FileNotFoundError:
            if not repair:
                return f"broken link preserved: {target}"
            target.unlink()
        else:
            if resolved == source:
                return f"linked: {target} -> {resolved}"
            if not repair:
                return f"conflict preserved: {target} -> {resolved}"
            target.unlink()
    elif target.exists():
        return f"directory conflict preserved: {target}"
    target.symlink_to(source, target_is_directory=target_is_directory)
    return f"linked: {target} -> {source}"


def uninstall_link(target: Path, source: Path) -> str:
    if not target.is_symlink():
        return f"left untouched (not a symlink): {target}"
    try:
        resolved = target.resolve(strict=True)
    except FileNotFoundError:
        resolved = None
    if resolved != source:
        return f"left untouched (points elsewhere): {target}"
    target.unlink()
    return f"removed link: {target}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "verify", "repair", "uninstall"), nargs="?", default="install")
    parser.add_argument("--scope", choices=("all", "both", "codex", "antigravity", "cli"), default="all")
    args = parser.parse_args()
    if not (REPO_ROOT / "SKILL.md").is_file():
        print(f"Missing SKILL.md in {REPO_ROOT}", file=sys.stderr)
        return 2
    targets = install_targets()
    selected_names = ("codex", "antigravity", "cli") if args.scope == "all" else (
        ("codex", "antigravity") if args.scope == "both" else (args.scope,)
    )
    results = []
    for name in selected_names:
        target, source, target_is_directory = targets[name]
        if args.action in {"install", "repair"}:
            result = install_link(target, source, target_is_directory=target_is_directory,
                                  repair=args.action == "repair")
        elif args.action == "uninstall":
            result = uninstall_link(target, source)
        else:
            good = target.is_symlink() and target.resolve(strict=False) == source
            result = f"verified: {target}" if good else f"missing or mismatched: {target}"
        results.append((name, result))
    for name, result in results:
        print(f"{name}: {result}")
    if args.action == "verify" and any(not value.startswith("verified:") for _, value in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
