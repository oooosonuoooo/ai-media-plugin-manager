#!/usr/bin/env python3
"""Create a verified, local-only backup of Krita and Kdenlive user state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional checkpoint directory; default uses XDG data home")
    args = parser.parse_args()
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser()
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    root = args.output.expanduser() if args.output else data_home / "ai-media-plugin-manager/checkpoints" / stamp
    if root.exists():
        raise SystemExit(f"Refusing to reuse an existing checkpoint directory: {root}")
    root.mkdir(parents=True, mode=0o700)
    sources = [
        home / ".config/kritarc",
        home / ".config/kritadisplayrc",
        home / ".config/kdenliverc",
        home / ".local/share/krita",
        home / ".local/share/kdenlive",
    ]
    files = []
    for source in sources:
        if not source.exists():
            files.append({"source": str(source), "status": "absent"})
            continue
        relative = Path("home") / source.relative_to(home)
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)
        items = [destination] if destination.is_file() else sorted(p for p in destination.rglob("*") if p.is_file() and not p.is_symlink())
        for copied in items:
            original = home / copied.relative_to(root).relative_to("home")
            copied_hash = digest(copied)
            if not original.is_file() or digest(original) != copied_hash:
                raise SystemExit(f"Checkpoint verification failed: {original}")
            files.append({"source": str(original), "backup": str(copied), "bytes": copied.stat().st_size, "sha256": copied_hash})
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checkpoint_root": str(root),
        "inputs": [str(p) for p in sources],
        "files": files,
        "privacy": "Local recovery data only. Do not publish editor configuration or resource profile contents.",
    }
    (root / "checkpoint-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"checkpoint_root": str(root), "copied_files": sum(1 for item in files if item.get("backup")), "bytes": sum(item.get("bytes", 0) for item in files), "verified": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
