#!/usr/bin/env python3
"""Read-only dependency and storage check for the media asset manager."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def command_version(command: str, args: list[str]) -> dict[str, str | bool]:
    path = shutil.which(command)
    if not path:
        return {"present": False}
    try:
        proc = subprocess.run([path, *args], capture_output=True, text=True, timeout=8, check=False)
        line = next((line.strip() for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()), "")
        return {"present": True, "path": path, "version_output": line[:240], "returncode": proc.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"present": True, "path": path, "version_output": f"error: {exc}"}


def main() -> int:
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser()
    config_path = config_home / "ai-media-plugin-manager/config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"Invalid config: {exc}"}, indent=2))
            return 2
    library = Path(os.environ.get("MEDIA_ASSET_LIBRARY", config.get("library_root", data_home / "ai-media-plugin-manager/assets"))).expanduser()
    data = {
        "python": {"version": sys.version.split()[0], "minimum": "3.10"},
        "commands": {
            "ffmpeg": command_version("ffmpeg", ["-version"]),
            "melt": command_version("melt", ["-version"]),
            "kdenlive": command_version("kdenlive", ["--version"]),
            "krita": command_version("krita", ["--version"]),
            "nvidia_smi": command_version("nvidia-smi", ["--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"]),
        },
        "paths": {
            "library_root": str(library),
            "library_exists": library.is_dir(),
            "krita_resources": str(home / ".local/share/krita"),
            "kdenlive_resources": str(home / ".local/share/kdenlive"),
            "config": str(config_path),
        },
    }
    try:
        probe = library
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        usage = shutil.disk_usage(probe)
        data["storage"] = {
            "free_bytes": usage.free,
            "free_gib": round(usage.free / (1024 ** 3), 2),
            "target_free_gb": int(config.get("target_free_space_gb", 200)),
            "minimum_free_space_gib": int(config.get("minimum_free_space_gib", 100)),
            "within_minimum_floor": usage.free >= int(config.get("minimum_free_space_gib", 100)) * (1024 ** 3),
        }
    except OSError as exc:
        data["storage"] = {"error": str(exc)}
    missing = [name for name in ("ffmpeg", "melt", "kdenlive", "krita") if not data["commands"][name]["present"]]
    data["missing_required_commands"] = missing
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
