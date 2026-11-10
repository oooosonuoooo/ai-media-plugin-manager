#!/usr/bin/env python3
"""Conservative local catalog and installer for creative media assets."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


VERSION = "0.1.0"
REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_SUFFIXES = {".cube", ".bundle", ".zip", ".kdenlivetitle", ".svg", ".json", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".flac", ".txt"}
LIBRARY_SUFFIXES = (SAFE_SUFFIXES - {".txt", ".zip"}) | {
    ".apng", ".blend", ".exr", ".gbr", ".gif", ".gpl", ".kra", ".kdenlive",
    ".kpl", ".kpp", ".mlt", ".mov", ".mp4", ".otf", ".pat", ".rawr", ".ttf", ".webm",
}
ALLOWED_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "www.peppercarrot.com",
    "peppercarrot.com",
    "files.krita.org",
    "krita.org",
    "kdenlive.org",
    "store.kde.org",
    "cdn.kde.org",
}


class ManagerError(Exception):
    """A safe, user-facing operation error."""


class HTTPSAllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Permit redirects only when they remain HTTPS on trusted hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https":
            raise ManagerError("Download redirect attempted to leave HTTPS")
        if parsed.hostname not in ALLOWED_HOSTS:
            raise ManagerError(f"Download redirect attempted to an untrusted host: {parsed.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def config_paths() -> dict[str, Any]:
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")).expanduser()
    config_file = config_home / "ai-media-plugin-manager/config.json"
    config: dict[str, Any] = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagerError(f"Cannot read local config {config_file}: {exc}") from exc
    library = Path(os.environ.get("MEDIA_ASSET_LIBRARY", config.get("library_root", data_home / "ai-media-plugin-manager/assets"))).expanduser()
    manifest = Path(os.environ.get("MEDIA_ASSET_MANIFEST", config.get("manifest", data_home / "ai-media-plugin-manager/installed.json"))).expanduser()
    state = Path(os.environ.get("MEDIA_ASSET_STATE", config.get("state_root", data_home / "ai-media-plugin-manager"))).expanduser()
    catalog = Path(os.environ.get("MEDIA_ASSET_CATALOG", REPO_ROOT / "manifests/catalog.json")).expanduser()
    return {"home": home, "data_home": data_home, "library": library, "manifest": manifest, "state": state, "catalog": catalog, "settings": config}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagerError(f"Cannot read JSON file {path}: {exc}") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    paths = config_paths()
    catalog_path = path or paths["catalog"]
    data = load_json(catalog_path)
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise ManagerError(f"Catalog must contain a resources list: {catalog_path}")
    seen: set[str] = set()
    for item in data["resources"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ManagerError("Every catalog resource must have a string id")
        if item["id"] in seen:
            raise ManagerError(f"Duplicate catalog id: {item['id']}")
        seen.add(item["id"])
    return data


def load_manifest(path: Path | None = None, *, create: bool = False) -> dict[str, Any]:
    paths = config_paths()
    manifest_path = path or paths["manifest"]
    data = load_json(manifest_path)
    if data is None:
        data = {"schema_version": 1, "resources": []}
        if create:
            write_json_atomic(manifest_path, data)
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise ManagerError(f"Install manifest must contain a resources list: {manifest_path}")
    return data


def save_manifest(data: dict[str, Any], path: Path | None = None) -> None:
    manifest_path = path or config_paths()["manifest"]
    write_json_atomic(manifest_path, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    name = Path(value).name
    if name != value or name in {"", ".", ".."} or "\x00" in name:
        raise ManagerError(f"Unsafe file name: {value!r}")
    suffix = Path(name).suffix.lower()
    if suffix not in SAFE_SUFFIXES:
        raise ManagerError(f"Unsupported resource file extension: {suffix or '(none)'}")
    return name


def reject_symlink_components(path: Path, context: str) -> None:
    """Reject paths that could redirect an operation through a symlink."""
    absolute = path.absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ManagerError(f"Refusing {context}: symbolic-link path components are not supported ({path})")


def validate_install_candidate(item: dict[str, Any]) -> None:
    if not isinstance(item.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", item["id"]):
        raise ManagerError("Catalog resource id contains unsafe path characters")
    version = item.get("version")
    if not isinstance(version, str) or len(version) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        raise ManagerError("Catalog resource version must be a safe single path component")
    if not item.get("installable", False):
        raise ManagerError(f"{item.get('id')} is cataloged for discovery only, not installation")
    if item.get("license_status") != "verified":
        raise ManagerError("License is not verified for this specific asset")
    if item.get("compatibility_status") != "verified":
        raise ManagerError("Compatibility is not verified for this application version")
    if item.get("executable", False) or item.get("resource_type") in {"python_plugin", "binary_plugin", "installer_script"}:
        raise ManagerError("Code and executable installers are not supported by the automatic asset installer")
    source_url = item.get("download_url", "")
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ManagerError("Download must use HTTPS from an explicitly trusted source host")
    if not item.get("version"):
        raise ManagerError("A pinned resource version is required")
    if parsed.hostname == "raw.githubusercontent.com" and not item.get("source_commit"):
        raise ManagerError("GitHub raw downloads must be pinned to an immutable commit")
    if parsed.hostname == "raw.githubusercontent.com":
        commit = item.get("source_commit")
        path_parts = urllib.parse.unquote(parsed.path).strip("/").split("/")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            raise ManagerError("GitHub raw downloads require a full 40-character commit hash")
        if len(path_parts) < 4 or path_parts[2].lower() != commit.lower():
            raise ManagerError("GitHub raw download URL revision must match source_commit")
    if not item.get("install_target"):
        raise ManagerError("A known application or library install_target is required")
    safe_name(item.get("filename", ""))


def resource_target(item: dict[str, Any], paths: dict[str, Path]) -> Path:
    home = paths["home"]
    target_map = {
        "studio:kdenlive/luts": paths["library"] / "kdenlive/luts",
        "studio:kdenlive/motion-graphics": paths["library"] / "kdenlive/motion-graphics",
        "studio:krita/bundles": paths["library"] / "krita/bundles",
        "studio:shared": paths["library"] / "shared",
        "krita:bundles": home / ".local/share/krita/bundles",
        "krita:templates": home / ".local/share/krita/templates",
        "kdenlive:titles": home / ".local/share/kdenlive/titles",
    }
    target = target_map.get(item["install_target"])
    if target is None:
        raise ManagerError(f"Unsupported install_target: {item['install_target']}")
    return target


def manager_owned_target(record: dict[str, Any], paths: dict[str, Any], catalog: dict[str, Any]) -> Path:
    """Return a manifest path only when it matches the catalog's allowed target."""
    asset_id = record.get("id")
    item = find_item(catalog, asset_id) if isinstance(asset_id, str) else None
    if item is None or not item.get("installable"):
        raise ManagerError(f"Cannot manage {asset_id!r}: it is not an installable catalog item")
    expected = resource_target(item, paths) / safe_name(item.get("installed_filename", item["filename"]))
    recorded_value = record.get("installation_path")
    if not isinstance(recorded_value, str) or not recorded_value:
        raise ManagerError(f"Refusing {asset_id}: manifest installation path is missing")
    recorded = Path(recorded_value).expanduser()
    if not recorded.is_absolute() or recorded.absolute() != expected.absolute():
        raise ManagerError(f"Refusing {asset_id}: manifest path is outside its catalog install target")
    reject_symlink_components(recorded, f"{asset_id}: symbolic-link install paths are not manager-owned files")
    return recorded


def manager_owned_cache(record: dict[str, Any], paths: dict[str, Any]) -> Path:
    """Return a cache file only when it remains inside this asset's manager cache."""
    asset_id = record.get("id")
    if not isinstance(asset_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", asset_id):
        raise ManagerError("Refusing repair: manifest resource id is missing")
    cache_value = record.get("cache_path")
    if not isinstance(cache_value, str) or not cache_value:
        raise ManagerError("Verified repair cache is unavailable; review the source and reinstall from the catalog")
    cache = Path(cache_value).expanduser()
    cache_root = Path(paths["state"]) / "cache" / asset_id
    try:
        if not cache.is_absolute() or cache.resolve(strict=False) == cache_root.resolve(strict=False) or not cache.resolve(strict=False).is_relative_to(cache_root.resolve(strict=False)):
            raise ManagerError("Refusing repair: manifest cache path is outside this asset's manager cache")
    except (OSError, RuntimeError) as exc:
        raise ManagerError(f"Refusing repair: cannot resolve manifest cache path: {exc}") from exc
    reject_symlink_components(cache, "repair through a symbolic-link cache path")
    return cache


def validate_cube(path: Path) -> dict[str, Any]:
    size = None
    rows = 0
    with path.open("r", encoding="utf-8", errors="strict") as stream:
        for raw in stream:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0].upper() == "LUT_3D_SIZE":
                if len(parts) != 2:
                    raise ManagerError("Malformed LUT_3D_SIZE declaration")
                try:
                    size = int(parts[1])
                except ValueError as exc:
                    raise ManagerError("LUT_3D_SIZE must be an integer") from exc
                if size < 2 or size > 128:
                    raise ManagerError(f"Unsupported LUT dimension: {size}")
                continue
            if parts[0].upper() in {"TITLE", "DOMAIN_MIN", "DOMAIN_MAX", "LUT_1D_SIZE"}:
                continue
            if len(parts) != 3:
                raise ManagerError(f"Invalid LUT data row: {line[:80]}")
            try:
                values = [float(v) for v in parts]
            except ValueError as exc:
                raise ManagerError(f"Invalid LUT data row: {line[:80]}") from exc
            if not all(math.isfinite(v) for v in values):
                raise ManagerError("LUT contains a non-finite channel value")
            rows += 1
    if size is None:
        raise ManagerError("LUT_3D_SIZE declaration was not found")
    expected = size ** 3
    if rows != expected:
        raise ManagerError(f"LUT has {rows} rows; expected {expected} for a {size}³ LUT")
    return {"format": "cube", "dimension": size, "rows": rows}


def validate_bundle(path: Path, *, max_uncompressed_bytes: int = 100_000_000) -> dict[str, Any]:
    if not zipfile.is_zipfile(path):
        raise ManagerError("Krita bundle is not a valid ZIP container")
    total = 0
    names: list[str] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len({info.filename for info in infos}) != len(infos):
            raise ManagerError("Krita bundle contains duplicate member paths")
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            raise ManagerError("Bundle expands beyond the configured inspection limit")
        for info in infos:
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or "\x00" in info.filename:
                raise ManagerError(f"Unsafe path in bundle: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ManagerError(f"Symbolic links are not allowed in bundles: {info.filename}")
            if member.suffix.lower() in {".py", ".pyc", ".pyo", ".sh", ".bat", ".cmd", ".exe", ".dll", ".so", ".desktop", ".js"}:
                raise ManagerError(f"Executable or plugin code is not allowed in static resource bundles: {info.filename}")
            total += info.file_size
            names.append(info.filename)
        bad = archive.testzip()
        if bad:
            raise ManagerError(f"Krita bundle contains a corrupt member: {bad}")
    if not names:
        raise ManagerError("Krita bundle is empty")
    return {"format": "krita_bundle_zip", "members": len(names), "uncompressed_bytes": total}


def validate_bundle_archive(path: Path, expected_member: str, *, max_uncompressed_bytes: int = 100_000_000) -> dict[str, Any]:
    expected_path = PurePosixPath(expected_member)
    if expected_path.is_absolute() or ".." in expected_path.parts or expected_path.suffix.lower() != ".bundle":
        raise ManagerError("Expected Krita bundle member must be a safe .bundle file path")
    if not zipfile.is_zipfile(path):
        raise ManagerError("Source archive is not a valid ZIP container")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len({info.filename for info in infos}) != len(infos):
            raise ManagerError("Source archive contains duplicate member paths")
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            raise ManagerError("Source archive expands beyond the configured inspection limit")
        for info in infos:
            member = PurePosixPath(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if member.is_absolute() or ".." in member.parts or mode == 0o120000:
                raise ManagerError(f"Unsafe member path or link in source archive: {info.filename}")
        bad = archive.testzip()
        if bad:
            raise ManagerError(f"Source archive contains a corrupt member: {bad}")
        matches = [info for info in archive.infolist() if info.filename == expected_member and not info.is_dir()]
        if len(matches) != 1:
            raise ManagerError(f"Expected exactly one {expected_member} member in source archive")
        info = matches[0]
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ManagerError("Krita bundle member cannot be a symbolic link")
        if info.file_size > max_uncompressed_bytes:
            raise ManagerError("Krita bundle exceeds the configured inspection limit")
        payload = archive.read(info)
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        bundle_infos = bundle.infolist()
        if len({info.filename for info in bundle_infos}) != len(bundle_infos):
            raise ManagerError("Krita bundle contains duplicate member paths")
        if sum(info.file_size for info in bundle_infos) > max_uncompressed_bytes:
            raise ManagerError("Krita bundle expands beyond the configured inspection limit")
        total = 0
        for member_info in bundle_infos:
            member_name = member_info.filename
            member = PurePosixPath(member_name)
            if member.is_absolute() or ".." in member.parts or "\x00" in member_name:
                raise ManagerError(f"Unsafe path in Krita bundle: {member_name}")
            mode = (member_info.external_attr >> 16) & 0o170000
            if mode == 0o120000 or member.suffix.lower() in {".py", ".pyc", ".pyo", ".sh", ".bat", ".cmd", ".exe", ".dll", ".so", ".desktop", ".js"}:
                raise ManagerError(f"Executable, symbolic-link, or plugin content is not allowed in static Krita bundles: {member_name}")
            total += member_info.file_size
        bad = bundle.testzip()
        if bad:
            raise ManagerError(f"Krita bundle contains a corrupt member: {bad}")
    if not payload:
        raise ManagerError("Krita bundle is empty")
    return {"format": "krita_bundle_zip", "archive_member": expected_member, "bundle_bytes": len(payload), "bundle_members": len(bundle.namelist()), "uncompressed_bytes": total}


def validate_resource_file(item: dict[str, Any], path: Path) -> dict[str, Any]:
    resource_type = item.get("resource_type")
    if resource_type == "cube_lut":
        return validate_cube(path)
    if resource_type == "krita_bundle":
        return validate_bundle(path, max_uncompressed_bytes=int(item.get("max_uncompressed_bytes", 100_000_000)))
    if resource_type == "krita_bundle_archive":
        return validate_bundle_archive(path, item["archive_member"], max_uncompressed_bytes=int(item.get("max_uncompressed_bytes", 100_000_000)))
    if not path.is_file() or path.stat().st_size == 0:
        raise ManagerError("Resource file is missing or empty")
    return {"format": resource_type or "static_file", "bytes": path.stat().st_size}


def download_file(item: dict[str, Any], dest: Path) -> dict[str, Any]:
    max_bytes = int(item.get("max_download_bytes", 50_000_000))
    request = urllib.request.Request(
        item["download_url"],
        headers={"User-Agent": f"ai-media-plugin-manager/{VERSION}", "Accept": "application/octet-stream"},
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(3):
        temp: Path | None = None
        try:
            opener = urllib.request.build_opener(HTTPSAllowlistedRedirectHandler())
            with opener.open(request, timeout=30) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                final_host = final_url.hostname
                if final_url.scheme != "https":
                    raise ManagerError("Download ended on a non-HTTPS URL")
                if final_host not in ALLOWED_HOSTS:
                    raise ManagerError(f"Download redirected to untrusted host: {final_host}")
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise ManagerError(f"Download exceeds the {max_bytes}-byte size limit")
                fd, temp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
                temp = Path(temp_name)
                total = 0
                digest = hashlib.sha256()
                with os.fdopen(fd, "wb") as output:
                    while True:
                        block = response.read(1024 * 256)
                        if not block:
                            break
                        total += len(block)
                        if total > max_bytes:
                            raise ManagerError(f"Download exceeds the {max_bytes}-byte size limit")
                        output.write(block)
                        digest.update(block)
                    output.flush()
                    os.fsync(output.fileno())
            expected = item.get("expected_sha256")
            observed = digest.hexdigest()
            if expected and observed.lower() != str(expected).lower():
                raise ManagerError(f"SHA-256 mismatch: expected {expected}, received {observed}")
            os.replace(temp, dest)
            return {"sha256": observed, "bytes": total, "expected_hash_published": bool(expected)}
        except ManagerError:
            if temp:
                temp.unlink(missing_ok=True)
            raise
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if temp:
                temp.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise ManagerError(f"Download failed after 3 attempts: {last_error}")


def confirm(prompt: str, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        raise ManagerError("Confirmation is required; rerun interactively or pass --yes after reviewing the candidate")
    answer = input(f"{prompt} [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise ManagerError("Cancelled")


def check_storage_budget(item: dict[str, Any], target_dir: Path, paths: dict[str, Any]) -> None:
    settings = paths.get("settings", {})
    floor_gib = int(settings.get("minimum_free_space_gib", 100))
    budget_gib = float(settings.get("initial_download_budget_gib", 2))
    probe = target_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        raise ManagerError(f"Cannot locate a filesystem for the install target: {target_dir}")
    free = shutil.disk_usage(probe).free
    floor_bytes = floor_gib * (1024 ** 3)
    if free < floor_bytes:
        raise ManagerError(f"Free space {free / (1024 ** 3):.2f} GiB is below the configured {floor_gib} GiB safety floor")
    cache_root = paths["state"] / "cache"
    cached = sum(p.stat().st_size for p in cache_root.rglob("*") if p.is_file()) if cache_root.exists() else 0
    per_item_limit = int(item.get("max_download_bytes", settings.get("max_asset_download_bytes", 50_000_000)))
    budget_bytes = int(budget_gib * (1024 ** 3))
    if cached + per_item_limit > budget_bytes:
        raise ManagerError(f"The configured {budget_gib:g} GiB download budget would be exceeded; review or increase it explicitly")


def find_item(catalog: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for item in catalog["resources"]:
        if item["id"] == asset_id:
            return item
    raise ManagerError(f"Unknown catalog id: {asset_id}")


def install_item(item: dict[str, Any], *, yes: bool = False, replace: bool = False) -> dict[str, Any]:
    validate_install_candidate(item)
    paths = config_paths()
    target_dir = resource_target(item, paths)
    target = target_dir / safe_name(item.get("installed_filename", item["filename"]))
    reject_symlink_components(target_dir, "install through a symbolic-link target path")
    manifest = load_manifest(create=True)
    existing_record = next((r for r in manifest["resources"] if r.get("id") == item["id"]), None)
    if (
        existing_record
        and existing_record.get("status") in {"installed", "verified"}
        and existing_record.get("version") == item.get("version")
    ):
        current = Path(existing_record.get("installation_path", "")).expanduser()
        if (
            current.absolute() == target.absolute()
            and not current.is_symlink()
            and current.is_file()
            and sha256_file(current) == existing_record.get("sha256")
        ):
            print(f"Already installed and unchanged: {current}")
            return existing_record
    confirm(
        f"Install {item['name']} {item['version']} ({item['license']}) to {target}?",
        yes,
    )
    state = paths["state"]
    check_storage_budget(item, target_dir, paths)
    cache = state / "cache" / item["id"] / f"{item['version']}-{safe_name(item['filename'])}"
    reject_symlink_components(cache, "download through a symbolic-link cache path")
    download_meta: dict[str, Any]
    if cache.is_file():
        cached_hash = sha256_file(cache)
        expected = item.get("expected_sha256")
        if expected and cached_hash.lower() != str(expected).lower():
            cache.unlink()
        else:
            download_meta = {"sha256": cached_hash, "bytes": cache.stat().st_size, "expected_hash_published": bool(expected)}
    if not cache.is_file():
        download_meta = download_file(item, cache)
    format_meta = validate_resource_file(item, cache)
    payload_cache = cache
    installed_resource_type = item.get("installed_resource_type", item.get("resource_type"))
    if item.get("archive_member"):
        payload_cache = cache.parent / f"{item['version']}-{download_meta['sha256'][:16]}-{safe_name(item['installed_filename'])}"
        reject_symlink_components(payload_cache, "extract to a symbolic-link cache path")
        with zipfile.ZipFile(cache) as archive:
            payload = archive.read(item["archive_member"])
        payload_hash = hashlib.sha256(payload).hexdigest()
        if not payload_cache.is_file() or sha256_file(payload_cache) != payload_hash:
            fd, temp_name = tempfile.mkstemp(prefix=f".{payload_cache.name}.", suffix=".part", dir=payload_cache.parent)
            temp_payload = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp_payload, payload_cache)
            finally:
                temp_payload.unlink(missing_ok=True)
        bundle_item = {**item, "resource_type": installed_resource_type}
        format_meta = validate_resource_file(bundle_item, payload_cache)
    installed_hash = sha256_file(payload_cache)
    installed_bytes = payload_cache.stat().st_size
    target_dir.mkdir(parents=True, exist_ok=True)
    reject_symlink_components(target, "install through a symbolic-link path")
    if target.exists():
        target_hash = sha256_file(target)
        if not replace:
            raise ManagerError(f"Refusing to overwrite existing file: {target}; use update after reviewing it")
        if not existing_record:
            raise ManagerError(f"Refusing to replace a file that is not recorded as manager-owned: {target}")
        recorded_path = Path(existing_record.get("installation_path", "")).expanduser()
        if recorded_path.absolute() != target.absolute():
            raise ManagerError(f"Refusing to replace a file outside the recorded manager-owned path: {target}")
        if target_hash != existing_record.get("sha256"):
            raise ManagerError(f"Refusing to replace a modified manager-owned file: {target}; use repair or resolve the conflict first")
        backup = state / "backups" / f"{item['id']}-{datetime.now().strftime('%Y%m%dT%H%M%S')}" / target.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    if not target.exists() or sha256_file(target) != installed_hash:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target_dir)
        os.close(fd)
        temp_target = Path(temp_name)
        try:
            shutil.copy2(payload_cache, temp_target)
            os.replace(temp_target, target)
        finally:
            temp_target.unlink(missing_ok=True)
    record = {
        "id": item["id"],
        "name": item["name"],
        "version": item["version"],
        "status": "installed",
        "resource_type": installed_resource_type,
        "application": item.get("application"),
        "source_url": item.get("source_url"),
        "download_url": item.get("download_url"),
        "source_commit": item.get("source_commit"),
        "author": item.get("author"),
        "license": item.get("license"),
        "license_url": item.get("license_url"),
        "commercial_use": item.get("commercial_use"),
        "attribution_required": item.get("attribution_required"),
        "attribution": item.get("attribution"),
        "ai_use_restrictions": item.get("ai_use_restrictions"),
        "sha256": installed_hash,
        "hash_source": "published_archive_hash_plus_extracted_asset_hash" if download_meta["expected_hash_published"] and item.get("archive_member") else ("published" if download_meta["expected_hash_published"] else "calculated_after_https_download"),
        "download_archive_sha256": download_meta["sha256"] if item.get("archive_member") else None,
        "download_archive_expected_sha256": item.get("expected_sha256") if item.get("archive_member") else None,
        "bytes": installed_bytes,
        "download_bytes": download_meta["bytes"],
        "cache_path": str(payload_cache),
        "installation_path": str(target),
        "compatible_applications": item.get("compatible_applications", []),
        "tested_application_versions": item.get("tested_application_versions", []),
        "installed_at": utc_now(),
        "update_status": "current",
        "validation_results": {
            "archive_or_format_integrity": {"status": "passed", "details": format_meta, "timestamp": utc_now()},
            "application_runtime": {"status": "pending", "details": item.get("runtime_test_note", "Run an application-level smoke test before marking verified")},
        },
    }
    if existing_record:
        manifest["resources"].remove(existing_record)
    manifest["resources"].append(record)
    save_manifest(manifest)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return record


def scan_counts() -> dict[str, Any]:
    home = Path.home()
    roots = {
        "krita": home / ".local/share/krita",
        "kdenlive": home / ".local/share/kdenlive",
    }
    result: dict[str, Any] = {}
    suffixes = {".bundle", ".kpp", ".gbr", ".gih", ".png", ".svg", ".cube", ".kdenlivetitle", ".xml"}
    for name, root in roots.items():
        counts: dict[str, int] = {}
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in suffixes:
                    counts[path.suffix.lower()] = counts.get(path.suffix.lower(), 0) + 1
        result[name] = {"path": str(root), "exists": root.is_dir(), "resource_files_by_extension": counts}
    return result


def github_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "per_page": min(max(limit, 1), 10), "sort": "stars"})
    url = f"https://api.github.com/search/repositories?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": f"ai-media-plugin-manager/{VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ManagerError(f"GitHub search failed: {exc}") from exc
    output = []
    for repo in data.get("items", []):
        license_data = repo.get("license") or {}
        output.append({
            "name": repo.get("full_name"),
            "url": repo.get("html_url"),
            "description": repo.get("description"),
            "license_spdx": license_data.get("spdx_id"),
            "archived": repo.get("archived"),
            "updated_at": repo.get("updated_at"),
            "stars": repo.get("stargazers_count"),
            "review_status": "repository metadata only; inspect asset-level license and compatibility before use",
        })
    return output


def search_local_resources(query: str) -> dict[str, Any]:
    paths = config_paths()
    catalog = load_catalog(paths["catalog"])["resources"]
    records = load_manifest(paths["manifest"])["resources"]
    query_terms = re.findall(r"\w+", query.casefold())

    def matches(*values: Any) -> bool:
        haystack = " ".join(str(value).casefold() for value in values)
        return all(term in haystack for term in query_terms)

    local_catalog = [item for item in catalog if matches(item)]
    catalog_matches = {item["id"] for item in local_catalog}
    installed_matches = []
    managed_paths = set()
    for record in records:
        raw_path = record.get("installation_path")
        if record.get("status") not in {"installed", "verified"} or not isinstance(raw_path, str) or not raw_path:
            continue
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            continue
        managed_paths.add(path.absolute())
        if record.get("id") in catalog_matches or matches(record):
            installed_matches.append(record)

    root = paths["library"]
    library_matches = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in LIBRARY_SUFFIXES or path.absolute() in managed_paths:
                continue
            relative_path = path.relative_to(root)
            if matches(relative_path) and not path.is_symlink() and path.is_file():
                library_matches.append({"path": str(path), "relative_path": str(relative_path)})
    return {
        "installed_matches": installed_matches,
        "library_matches": library_matches,
        "local_catalog": local_catalog,
    }


def cmd_search(args: argparse.Namespace) -> None:
    result = search_local_resources(args.query)
    if args.online:
        result["github_candidates"] = github_search(args.query)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    installed_matches = result["installed_matches"]
    print(f"Installed matches: {len(installed_matches)}")
    for record in installed_matches:
        print(f"- {record.get('id')} [{record['status']}] {record['installation_path']}")
    library_matches = result["library_matches"]
    print(f"Other library files: {len(library_matches)} (matched by path, review provenance before use)")
    for entry in library_matches:
        print(f"- {entry['path']}")
    local_catalog = result["local_catalog"]
    print(f"Local catalog: {len(local_catalog)} match(es)")
    for item in local_catalog:
        print(f"- {item['id']} [{item.get('status', 'discovered')}] {item['name']} — {item.get('license', 'license unresolved')}")
        if item.get("notes"):
            print(f"  {item['notes']}")
    if args.online:
        print("\nGitHub candidates (repository metadata only; do not install without per-asset review):")
        for item in result.get("github_candidates", []):
            print(f"- {item.get('name')} | license={item.get('license_spdx') or 'unidentified'} | {item.get('url')}")
            if item.get("description"):
                print(f"  {item['description']}")


def cmd_catalog(args: argparse.Namespace) -> None:
    data = load_catalog()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print(f"Catalog: {len(data['resources'])} resource record(s)")
    for item in data["resources"]:
        print(f"- {item['id']} [{item.get('status', 'discovered')}] {item['name']} — {item.get('license', 'license unresolved')}")


def cmd_list(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    output = {"managed_resources": manifest["resources"], "detected_resource_roots": scan_counts()}
    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return
    print(f"Manager-tracked resources: {len(manifest['resources'])}")
    for item in manifest["resources"]:
        print(f"- {item.get('id')} [{item.get('status')}] {item.get('installation_path')}")
    print("\nDetected editor resource roots (these counts do not imply manager ownership):")
    for app, value in output["detected_resource_roots"].items():
        print(f"- {app}: {value['path']} — {value['resource_files_by_extension']}")


def cmd_install(args: argparse.Namespace) -> None:
    item = find_item(load_catalog(), args.asset_id)
    install_item(item, yes=args.yes, replace=args.replace)


def verify_record(item: dict[str, Any], *, app_smoke: bool = False) -> dict[str, Any]:
    path = Path(item.get("installation_path", ""))
    result: dict[str, Any] = {"id": item.get("id"), "path": str(path), "checks": {}}
    if not path.is_file():
        result["checks"]["exists"] = "failed"
        return result
    observed = sha256_file(path)
    result["checks"]["exists"] = "passed"
    result["checks"]["sha256"] = "passed" if observed == item.get("sha256") else "failed"
    try:
        if item.get("resource_type") == "krita_bundle":
            format_data = validate_bundle(path)
        elif item.get("resource_type") == "cube_lut":
            format_data = validate_cube(path)
        else:
            format_data = {"bytes": path.stat().st_size}
        result["checks"]["format_integrity"] = {"status": "passed", **format_data}
    except (ManagerError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        result["checks"]["format_integrity"] = {"status": "failed", "reason": str(exc)}
    if app_smoke and item.get("resource_type") == "cube_lut":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            result["checks"]["ffmpeg_lut_smoke"] = {"status": "unavailable", "reason": "ffmpeg is not on PATH"}
        else:
            filter_arg = f"lut3d=file='{path.as_posix()}'"
            command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=16x16:d=0.04", "-vf", filter_arg, "-frames:v", "1", "-f", "null", "-"]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            result["checks"]["ffmpeg_lut_smoke"] = {"status": "passed" if proc.returncode == 0 else "failed", "returncode": proc.returncode, "stderr": proc.stderr[-1000:]}
    elif app_smoke:
        result["checks"]["application_smoke"] = {"status": "not_run", "reason": "No automated editor-specific smoke test is registered for this resource type"}
    return result


def cmd_verify(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    selected = [r for r in manifest["resources"] if args.asset_id is None or r.get("id") == args.asset_id]
    if args.asset_id and not selected:
        raise ManagerError(f"No installed resource with id {args.asset_id}")
    results = [verify_record(item, app_smoke=args.app_smoke) for item in selected]
    for item, result in zip(selected, results):
        item.setdefault("validation_results", {})["manager_verify"] = {"status": "passed" if all(v == "passed" or (isinstance(v, dict) and v.get("status") in {"passed", "not_run", "unavailable"}) for v in result["checks"].values()) else "failed", "result": result, "timestamp": utc_now()}
        ffmpeg_check = result["checks"].get("ffmpeg_lut_smoke")
        if ffmpeg_check and isinstance(ffmpeg_check, dict):
            item["validation_results"]["ffmpeg_lut_smoke"] = {"status": ffmpeg_check.get("status"), "details": ffmpeg_check, "timestamp": utc_now()}
    if selected:
        save_manifest(manifest)
    print(json.dumps(results, indent=2, ensure_ascii=False) if args.json else "\n".join(f"{r['id']}: {r['checks']}" for r in results))
    failures = [r["id"] for item, r in zip(selected, results) if item.get("validation_results", {}).get("manager_verify", {}).get("status") == "failed"]
    if failures:
        raise ManagerError(f"Verification failed for: {', '.join(failures)}")


def cmd_update(args: argparse.Namespace) -> None:
    catalog = load_catalog()
    manifest = load_manifest()
    records = manifest["resources"]
    selected = [r for r in records if args.asset_id is None or r.get("id") == args.asset_id]
    if args.asset_id and not selected:
        raise ManagerError(f"No installed resource with id {args.asset_id}")
    changes = []
    for record in selected:
        try:
            item = find_item(catalog, record["id"])
        except ManagerError:
            changes.append({"id": record.get("id"), "update_status": "not_in_catalog"})
            continue
        latest = item.get("version")
        status = "current" if latest == record.get("version") else "update_available"
        record["update_status"] = status
        changes.append({"id": record.get("id"), "installed": record.get("version"), "catalog": latest, "update_status": status})
    save_manifest(manifest)
    if args.apply:
        confirm("Apply the catalog updates listed above? Existing managed copies will be backed up.", args.yes)
        for change in changes:
            if change.get("update_status") != "update_available":
                continue
            item = find_item(catalog, change["id"])
            updated = install_item(item, yes=True, replace=True)
            change["installed"] = updated["version"]
            change["update_status"] = "updated"
    print(json.dumps(changes, indent=2, ensure_ascii=False))


def cmd_repair(args: argparse.Namespace) -> None:
    paths = config_paths()
    catalog = load_catalog(paths["catalog"])
    manifest = load_manifest()
    record = next((r for r in manifest["resources"] if r.get("id") == args.asset_id), None)
    if not record:
        raise ManagerError(f"No installed resource with id {args.asset_id}")
    target = manager_owned_target(record, paths, catalog)
    cache = manager_owned_cache(record, paths)
    expected = record.get("sha256")
    if target.is_file() and sha256_file(target) == expected:
        print(f"Healthy; no repair needed: {target}")
        return
    if not cache.is_file() or sha256_file(cache) != expected:
        raise ManagerError("Verified repair cache is unavailable; review the source and reinstall from the catalog")
    if not args.apply:
        print(f"Repair available from the verified cache for {target}; rerun with --apply --yes")
        return
    confirm(f"Restore the managed resource at {target}?", args.yes)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file():
            raise ManagerError(f"Refusing to replace a non-file install target: {target}")
        quarantine = paths["state"] / "quarantine" / f"{record['id']}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(quarantine))
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".repair", dir=target.parent)
    os.close(fd)
    temp_target = Path(temp_name)
    try:
        shutil.copy2(cache, temp_target)
        os.replace(temp_target, target)
    finally:
        temp_target.unlink(missing_ok=True)
    record["status"] = "installed"
    record.setdefault("validation_results", {})["repair"] = {"status": "restored_from_verified_cache", "timestamp": utc_now()}
    save_manifest(manifest)
    print(f"Restored: {target}")


def cmd_cleanup(args: argparse.Namespace) -> None:
    paths = config_paths()
    catalog = load_catalog(paths["catalog"])
    manifest = load_manifest()
    selected = [r for r in manifest["resources"] if args.asset_id is None or r.get("id") == args.asset_id]
    if args.asset_id and not selected:
        raise ManagerError(f"No installed resource with id {args.asset_id}")
    if not selected:
        print("No manager-owned resources to clean up")
        return
    owned = [(record, manager_owned_target(record, paths, catalog)) for record in selected]
    eligible = []
    for record, path in owned:
        unchanged = path.is_file() and sha256_file(path) == record.get("sha256")
        if unchanged:
            eligible.append((record, path))
            print(f"Would remove {path} ({record.get('id')})" if not args.apply else f"Ready to remove {path} ({record.get('id')})")
        else:
            print(f"Leaving missing or modified file untouched: {path} ({record.get('id')})")
    if not args.apply:
        print("Dry run only. Use --apply --yes to remove unchanged manager-owned files.")
        return
    if not eligible:
        print("No unchanged manager-owned files to remove")
        return
    confirm("Remove the listed unchanged manager-owned resources?", args.yes)
    removed = []
    for record, path in eligible:
        if path.is_file() and not path.is_symlink() and sha256_file(path) == record.get("sha256"):
            path.unlink()
            record["status"] = "removed"
            record["removed_at"] = utc_now()
            removed.append(record["id"])
        else:
            record["cleanup_status"] = "left_untouched_missing_or_modified"
    save_manifest(manifest)
    print(json.dumps({"removed": removed}, indent=2))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="media-assets", description="Discover and manage legally reviewed creative assets")
    parser.add_argument("--version", action="version", version=f"media-assets {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search", help="Search installed resources, library files, and catalog candidates")
    p.add_argument("query")
    p.add_argument("--online", action="store_true", help="Add GitHub repository candidates; these remain unverified")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("catalog", help="Show discovered, deferred, and unsupported candidates")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_catalog)
    p = sub.add_parser("list", help="List manager-tracked resources and detect editor resource roots")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("install", help="Install a reviewed static asset from the catalog")
    p.add_argument("asset_id")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--replace", action="store_true", help="Back up and replace an existing manager-owned copy")
    p.set_defaults(func=cmd_install)
    p = sub.add_parser("verify", help="Check installed hashes and resource formats")
    p.add_argument("asset_id", nargs="?")
    p.add_argument("--app-smoke", action="store_true", help="Run a small supported application/filter smoke test")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("update", help="Check the catalog for version changes; application requires --apply")
    p.add_argument("asset_id", nargs="?")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_update)
    p = sub.add_parser("repair", help="Restore an unchanged manager-owned resource from its verified cache")
    p.add_argument("asset_id")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_repair)
    p = sub.add_parser("cleanup", help="Remove only unchanged manager-owned assets (dry run by default)")
    p.add_argument("asset_id", nargs="?")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_cleanup)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except (ManagerError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"media-assets: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
