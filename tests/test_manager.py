import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from scripts import media_assets as manager

FULL_COMMIT = "a" * 40


class LauncherAndDiscoveryTests(unittest.TestCase):
    def test_installed_symlink_runs_the_cli_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "media-assets"
            launcher.symlink_to(manager.REPO_ROOT / "scripts" / "media-assets")
            output = subprocess.check_output([str(launcher), "--version"], cwd=tmp, text=True)
        self.assertEqual(output.strip(), f"media-assets {manager.VERSION}")

    def test_search_distinguishes_installed_files_from_catalog_and_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "live.cube"
            installed.touch()
            template = root / "logo-reveal.rawr"
            template.touch()
            catalog = {"resources": [
                {"id": "live", "category": "logo reveal"},
                {"id": "missing", "category": "logo reveal"},
            ]}
            manifest = {"resources": [
                {"id": "live", "status": "verified", "installation_path": str(installed)},
                {"id": "missing", "status": "verified", "installation_path": str(root / "missing.cube")},
            ]}
            paths = {"library": root, "catalog": root / "catalog.json", "manifest": root / "installed.json"}
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "load_catalog", return_value=catalog),
                patch.object(manager, "load_manifest", return_value=manifest),
            ):
                result = manager.search_local_resources("logo reveal")
        self.assertEqual([item["id"] for item in result["installed_matches"]], ["live"])
        self.assertEqual([item["relative_path"] for item in result["library_matches"]], [template.name])
        self.assertEqual([item["id"] for item in result["local_catalog"]], ["missing"])

    def test_search_returns_external_index_metadata_and_live_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            library.mkdir()
            asset = library / "rnnoise.so"
            asset.write_bytes(b"verified plugin fixture")
            index_path = root / "local-inventory.json"
            index_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "rnnoise-local",
                "name": "RNNoise voice denoiser",
                "status": "verified",
                "application": "Kdenlive",
                "license": "GPL-3.0",
                "installation_path": str(asset),
                "files": [{"path": str(asset), "sha256": manager.sha256_file(asset)}],
            }]}), encoding="utf-8")
            paths = {"library": root / "library", "catalog": root / "catalog.json", "manifest": root / "installed.json", "index": index_path}
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "load_catalog", return_value={"resources": []}),
                patch.object(manager, "load_manifest", return_value={"resources": []}),
            ):
                result = manager.search_local_resources("Kdenlive GPL denoiser")
        self.assertEqual([item["id"] for item in result["indexed_matches"]], ["rnnoise-local"])
        self.assertEqual(result["indexed_matches"][0]["observed_presence"], "present")
        self.assertEqual(result["indexed_matches"][0]["license"], "GPL-3.0")
        self.assertEqual(result["library_matches"], [])

    def test_search_does_not_list_an_indexed_resource_source_manifest_as_an_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library" / "kdenlive" / "motion-graphics"
            library.mkdir(parents=True)
            source_manifest = library / "asset-manifest.json"
            source_manifest.write_text("{}", encoding="utf-8")
            index_path = root / "local-inventory.json"
            inventory = {"resources": [{
                "id": "motion-pack",
                "name": "Motion graphics pack",
                "status": "verified",
                "installation_path": str(library),
                "files": [],
                "source_manifest": str(source_manifest),
            }]}
            paths = {"library": root / "library", "catalog": root / "catalog.json", "manifest": root / "installed.json", "index": index_path}
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "load_catalog", return_value={"resources": []}),
                patch.object(manager, "load_manifest", return_value={"resources": []}),
                patch.object(manager, "load_local_inventory", return_value=inventory),
            ):
                result = manager.search_local_resources("motion graphics")
        self.assertEqual([item["id"] for item in result["indexed_matches"]], ["motion-pack"])
        self.assertEqual(result["library_matches"], [])

    def test_search_ignores_schema_keys_and_null_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = {"resources": [{
                "id": "krita-brushes",
                "name": "AL Paint",
                "application": "Krita",
                "category": "brush bundle",
                "template_count": None,
            }]}
            paths = {
                "library": root,
                "catalog": root / "catalog.json",
                "manifest": root / "installed.json",
                "index": root / "local-inventory.json",
            }
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "load_catalog", return_value={"resources": []}),
                patch.object(manager, "load_manifest", return_value={"resources": []}),
                patch.object(manager, "load_local_inventory", return_value=inventory),
            ):
                result = manager.search_local_resources("Krita template")
        self.assertEqual(result["indexed_matches"], [])

    def test_external_inventory_path_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(manager.os.environ, {"XDG_DATA_HOME": tmp, "MEDIA_ASSET_INDEX": str(Path(tmp) / "custom.json")}):
            self.assertEqual(manager.config_paths()["index"], Path(tmp) / "custom.json")


class ExternalInventoryVerificationTests(unittest.TestCase):
    def test_verify_reports_hash_and_presence_separately_for_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hashed = root / "with-hash.bin"
            unhashed = root / "without-hash.bin"
            hashed.write_bytes(b"known bytes")
            unhashed.write_bytes(b"present but not pinned")
            item = {
                "id": "external-pack",
                "files": [
                    {"path": str(hashed), "sha256": manager.sha256_file(hashed)},
                    {"path": str(unhashed), "sha256": None},
                ],
            }
            result = manager.verify_indexed_record(item)
        check = result["checks"]["file_integrity"]
        self.assertEqual(check["status"], "unverified")
        self.assertEqual(check["files_total"], 2)
        self.assertEqual(check["entries"][0]["presence"], "passed")
        self.assertEqual(check["entries"][0]["sha256"], "passed")
        self.assertEqual(check["entries"][1]["presence"], "passed")
        self.assertEqual(check["entries"][1]["sha256"], "not_recorded")

    def test_verify_reads_external_index_without_saving_manager_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "external.bin"
            asset.write_bytes(b"external bytes")
            index = {"resources": [{
                "id": "external-record",
                "files": [{"path": str(asset), "sha256": manager.sha256_file(asset)}],
            }]}
            with (
                patch.object(manager, "load_manifest", return_value={"resources": []}),
                patch.object(manager, "load_local_inventory", return_value=index),
                patch.object(manager, "save_manifest") as save_manifest,
                redirect_stdout(StringIO()) as output,
            ):
                manager.cmd_verify(Namespace(asset_id="external-record", app_smoke=False, json=True))
        save_manifest.assert_not_called()
        self.assertIn('"status": "passed"', output.getvalue())

    def test_cleanup_does_not_manage_external_inventory_records(self):
        with (
            patch.object(manager, "load_catalog", return_value={"resources": []}),
            patch.object(manager, "load_manifest", return_value={"resources": []}),
            redirect_stdout(StringIO()) as output,
        ):
            manager.cmd_cleanup(Namespace(asset_id=None, apply=False, yes=False))
        self.assertIn("No manager-owned resources to clean up", output.getvalue())


class SafePathTests(unittest.TestCase):
    def test_rejects_path_traversal(self):
        with self.assertRaises(manager.ManagerError):
            manager.safe_name("../outside.cube")

    def test_rejects_executable_extension(self):
        with self.assertRaises(manager.ManagerError):
            manager.safe_name("install.sh")

    def test_accepts_cube_filename(self):
        self.assertEqual(manager.safe_name("look.cube"), "look.cube")


class LicenseAndSourceGates(unittest.TestCase):
    def test_rejects_unverified_license(self):
        item = {
            "id": "unclear", "name": "Unclear", "installable": True,
            "license_status": "unclear", "compatibility_status": "verified",
            "version": "1", "download_url": "https://raw.githubusercontent.com/x/y/abc/file.cube",
            "source_commit": "abc", "install_target": "studio:kdenlive/luts", "filename": "file.cube",
        }
        with self.assertRaisesRegex(manager.ManagerError, "License"):
            manager.validate_install_candidate(item)

    def test_rejects_unpinned_or_non_https_download(self):
        item = {
            "id": "unsafe", "name": "Unsafe", "installable": True,
            "license_status": "verified", "compatibility_status": "verified",
            "version": "1", "download_url": "http://example.org/file.cube",
            "install_target": "studio:kdenlive/luts", "filename": "file.cube",
        }
        with self.assertRaisesRegex(manager.ManagerError, "HTTPS"):
            manager.validate_install_candidate(item)

    def test_rejects_path_traversal_in_catalog_id_and_version(self):
        item = {
            "id": "../outside", "name": "Unsafe", "installable": True,
            "license_status": "verified", "compatibility_status": "verified",
            "version": "1", "license": "CC0-1.0",
            "download_url": "https://raw.githubusercontent.com/x/y/abc/file.cube",
            "source_commit": "abc", "install_target": "studio:kdenlive/luts", "filename": "file.cube",
        }
        with self.assertRaisesRegex(manager.ManagerError, "resource id"):
            manager.validate_install_candidate(item)
        item["id"] = "safe-resource"
        item["version"] = "../../outside"
        with self.assertRaisesRegex(manager.ManagerError, "version"):
            manager.validate_install_candidate(item)

    def test_raw_download_revision_must_match_full_source_commit(self):
        item = {
            "id": "safe-resource", "name": "Safe", "installable": True,
            "license_status": "verified", "compatibility_status": "verified",
            "version": "1", "license": "CC0-1.0",
            "download_url": "https://raw.githubusercontent.com/x/y/main/file.cube",
            "source_commit": FULL_COMMIT, "install_target": "studio:kdenlive/luts", "filename": "file.cube",
        }
        with self.assertRaisesRegex(manager.ManagerError, "revision must match"):
            manager.validate_install_candidate(item)
        item["download_url"] = f"https://raw.githubusercontent.com/x/y/{FULL_COMMIT}/file.cube"
        item["source_commit"] = "abc123"
        with self.assertRaisesRegex(manager.ManagerError, "full 40-character"):
            manager.validate_install_candidate(item)

    def test_redirect_handler_rejects_http_downgrade_and_untrusted_host(self):
        handler = manager.HTTPSAllowlistedRedirectHandler()
        request = manager.urllib.request.Request("https://raw.githubusercontent.com/x/y/file")
        with self.assertRaisesRegex(manager.ManagerError, "leave HTTPS"):
            handler.redirect_request(request, None, 302, "Found", {}, "http://raw.githubusercontent.com/x/y/file")
        with self.assertRaisesRegex(manager.ManagerError, "untrusted host"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://example.org/file")


class CubeValidationTests(unittest.TestCase):
    def write_cube(self, path: Path, rows: int) -> None:
        lines = ["TITLE \"test\"", "LUT_3D_SIZE 2"]
        lines.extend("0.0 0.0 0.0" for _ in range(rows))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_accepts_valid_2_cube(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.cube"
            self.write_cube(path, 8)
            result = manager.validate_cube(path)
            self.assertEqual(result["dimension"], 2)
            self.assertEqual(result["rows"], 8)

    def test_rejects_wrong_row_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cube"
            self.write_cube(path, 7)
            with self.assertRaisesRegex(manager.ManagerError, "expected 8"):
                manager.validate_cube(path)

    def test_rejects_nan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cube"
            path.write_text("LUT_3D_SIZE 2\n" + "nan 0 0\n" * 8, encoding="utf-8")
            with self.assertRaisesRegex(manager.ManagerError, "non-finite"):
                manager.validate_cube(path)

    def test_rejects_noninteger_lut_dimension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cube"
            path.write_text("LUT_3D_SIZE large\n", encoding="utf-8")
            with self.assertRaisesRegex(manager.ManagerError, "must be an integer"):
                manager.validate_cube(path)


class BundleValidationTests(unittest.TestCase):
    def test_install_replaces_modified_extracted_cache_with_archive_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir = root / "state" / "cache" / "test-bundle"
            cache_dir.mkdir(parents=True)
            original = io.BytesIO()
            with zipfile.ZipFile(original, "w") as bundle:
                bundle.writestr("paintoppresets/original.kpp", b"original")
            archive = cache_dir / "1-pack.zip"
            with zipfile.ZipFile(archive, "w") as pack:
                pack.writestr("test.bundle", original.getvalue())
            archive_hash = manager.sha256_file(archive)
            extracted = cache_dir / f"1-{archive_hash[:16]}-test.bundle"
            with zipfile.ZipFile(extracted, "w") as bundle:
                bundle.writestr("paintoppresets/modified.kpp", b"modified")
            paths = {
                "home": root, "library": root / "library", "manifest": root / "installed.json",
                "state": root / "state", "catalog": root / "catalog.json", "settings": {},
            }
            item = {
                "id": "test-bundle", "name": "Test Bundle", "version": "1",
                "installable": True, "license": "CC0-1.0", "license_status": "verified",
                "compatibility_status": "verified", "filename": "pack.zip",
                "archive_member": "test.bundle", "installed_filename": "test.bundle",
                "resource_type": "krita_bundle_archive", "installed_resource_type": "krita_bundle",
                "install_target": "studio:krita/bundles", "expected_sha256": archive_hash,
                "download_url": f"https://raw.githubusercontent.com/x/y/{FULL_COMMIT}/pack.zip",
                "source_commit": FULL_COMMIT,
            }
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "check_storage_budget"),
                redirect_stdout(StringIO()),
            ):
                record = manager.install_item(item, yes=True)
            self.assertEqual(Path(record["installation_path"]).read_bytes(), original.getvalue())
            self.assertEqual(extracted.read_bytes(), original.getvalue())

    def test_validates_bundle_archive_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.zip"
            bundle = io.BytesIO()
            with zipfile.ZipFile(bundle, "w") as inner:
                inner.writestr("paintoppresets/test.kpp", b"sample preset")
            with zipfile.ZipFile(path, "w") as outer:
                outer.writestr("pack/test.bundle", bundle.getvalue())
            info = manager.validate_bundle_archive(path, "pack/test.bundle")
            self.assertEqual(info["archive_member"], "pack/test.bundle")

    def test_rejects_archive_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../escape.bundle", b"bad")
            with self.assertRaises(manager.ManagerError):
                manager.validate_bundle_archive(path, "../escape.bundle")

    def test_rejects_plugin_code_in_static_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.bundle"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("pykrita/plugin.py", "print('unsafe')")
            with self.assertRaisesRegex(manager.ManagerError, "plugin code"):
                manager.validate_bundle(path)


class CatalogTests(unittest.TestCase):
    def test_catalog_ids_are_unique_and_installable_entries_pass_gates(self):
        catalog = manager.load_catalog(Path(__file__).parents[1] / "manifests/catalog.json")
        ids = [item["id"] for item in catalog["resources"]]
        self.assertEqual(len(ids), len(set(ids)))
        allowed_statuses = {"discovered", "downloaded", "installed", "verified", "failed", "deferred", "unsupported"}
        for item in catalog["resources"]:
            self.assertIn(item.get("status", "discovered"), allowed_statuses, item["id"])
            if item.get("installable"):
                manager.validate_install_candidate(item)

    def test_config_can_override_library_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_home = Path(tmp) / "config"
            data_home = Path(tmp) / "data"
            target = Path(tmp) / "creative-library"
            config_file = cfg_home / "ai-media-plugin-manager/config.json"
            config_file.parent.mkdir(parents=True)
            config_file.write_text(json.dumps({"library_root": str(target)}), encoding="utf-8")
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(cfg_home), "XDG_DATA_HOME": str(data_home)}, clear=False):
                paths = manager.config_paths()
            self.assertEqual(paths["library"], target)


class UpdateTests(unittest.TestCase):
    def _item(self, version="2"):
        return {
            "id": "test-resource",
            "name": "Test Resource",
            "license": "CC0-1.0",
            "version": version,
            "installable": True,
            "license_status": "verified",
            "compatibility_status": "verified",
            "download_url": f"https://raw.githubusercontent.com/example/project/{FULL_COMMIT}/test.txt",
            "source_commit": FULL_COMMIT,
            "install_target": "studio:kdenlive/luts",
            "filename": "test.txt",
            "resource_type": "static_file",
        }

    def _download_new_version(self, candidate, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("version two", encoding="utf-8")
        return {
            "sha256": manager.sha256_file(destination),
            "bytes": destination.stat().st_size,
            "expected_hash_published": False,
        }

    def test_installs_new_catalog_version_when_existing_copy_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            state = root / "state"
            manifest_path = root / "installed.json"
            target = library / "kdenlive/luts/test.txt"
            target.parent.mkdir(parents=True)
            target.write_text("version one", encoding="utf-8")
            old_hash = manager.sha256_file(target)
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "test-resource",
                "version": "1",
                "status": "installed",
                "sha256": old_hash,
                "installation_path": str(target),
            }]}), encoding="utf-8")
            paths = {
                "home": root,
                "library": library,
                "manifest": manifest_path,
                "state": state,
                "catalog": root / "catalog.json",
                "settings": {},
            }
            item = {
                "id": "test-resource",
                "name": "Test Resource",
                "license": "CC0-1.0",
                "version": "2",
                "installable": True,
                "license_status": "verified",
                "compatibility_status": "verified",
                "download_url": f"https://raw.githubusercontent.com/example/project/{FULL_COMMIT}/test.txt",
                "source_commit": FULL_COMMIT,
                "install_target": "studio:kdenlive/luts",
                "filename": "test.txt",
                "resource_type": "static_file",
            }

            def download_new_version(candidate, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("version two", encoding="utf-8")
                return {
                    "sha256": manager.sha256_file(destination),
                    "bytes": destination.stat().st_size,
                    "expected_hash_published": False,
                }

            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "check_storage_budget"),
                patch.object(manager, "download_file", side_effect=download_new_version),
            ):
                record = manager.install_item(item, yes=True, replace=True)

            self.assertEqual(record["version"], "2")
            self.assertEqual(target.read_text(encoding="utf-8"), "version two")
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["resources"]), 1)
            self.assertEqual(saved["resources"][0]["version"], "2")
            backups = list((state / "backups").glob("test-resource-*/test.txt"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "version one")

    def test_update_apply_reports_updated_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            state = root / "state"
            manifest_path = root / "installed.json"
            target = library / "kdenlive/luts/test.txt"
            target.parent.mkdir(parents=True)
            target.write_text("version one", encoding="utf-8")
            item = self._item()
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": item["id"], "version": "1", "status": "installed",
                "sha256": manager.sha256_file(target), "installation_path": str(target),
            }]}), encoding="utf-8")
            paths = {"home": root, "library": library, "manifest": manifest_path,
                     "state": state, "catalog": root / "catalog.json", "settings": {}}
            output = StringIO()
            real_install = manager.install_item

            def quiet_install(candidate, *, yes=False, replace=False):
                with redirect_stdout(StringIO()):
                    return real_install(candidate, yes=yes, replace=replace)

            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "load_catalog", return_value={"resources": [item]}),
                patch.object(manager, "check_storage_budget"),
                patch.object(manager, "download_file", side_effect=self._download_new_version),
                patch.object(manager, "install_item", side_effect=quiet_install),
                redirect_stdout(output),
            ):
                manager.cmd_update(Namespace(asset_id=None, apply=True, yes=True))
            changes = json.loads(output.getvalue())
            self.assertEqual(changes[0]["update_status"], "updated")
            self.assertEqual(changes[0]["installed"], "2")

    def test_replace_refuses_modified_manager_owned_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            state = root / "state"
            target = library / "kdenlive/luts/test.txt"
            target.parent.mkdir(parents=True)
            target.write_text("user edit", encoding="utf-8")
            manifest_path = root / "installed.json"
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "test-resource", "version": "1", "status": "installed",
                "sha256": "original-hash",
                "installation_path": str(target),
            }]}), encoding="utf-8")
            paths = {"home": root, "library": library, "manifest": manifest_path,
                     "state": state, "catalog": root / "catalog.json", "settings": {}}
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "check_storage_budget"),
                patch.object(manager, "download_file", side_effect=self._download_new_version),
            ):
                with self.assertRaisesRegex(manager.ManagerError, "modified manager-owned"):
                    manager.install_item(self._item(), yes=True, replace=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "user edit")

    def test_replace_refuses_untracked_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            target = library / "kdenlive/luts/test.txt"
            target.parent.mkdir(parents=True)
            target.write_text("untracked file", encoding="utf-8")
            manifest_path = root / "installed.json"
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": []}), encoding="utf-8")
            paths = {"home": root, "library": library, "manifest": manifest_path,
                     "state": root / "state", "catalog": root / "catalog.json", "settings": {}}
            with (
                patch.object(manager, "config_paths", return_value=paths),
                patch.object(manager, "check_storage_budget"),
                patch.object(manager, "download_file", side_effect=self._download_new_version),
            ):
                with self.assertRaisesRegex(manager.ManagerError, "not recorded as manager-owned"):
                    manager.install_item(self._item(), yes=True, replace=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "untracked file")


class ManifestSafetyTests(unittest.TestCase):
    def _catalog(self):
        return {"resources": [{
            "id": "safe-resource", "name": "Safe Resource", "installable": True,
            "install_target": "studio:kdenlive/luts", "filename": "safe.cube",
        }]}

    def test_cleanup_refuses_tampered_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            external = root / "outside.cube"
            external.write_text("keep me", encoding="utf-8")
            manifest_path = root / "installed.json"
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "safe-resource", "installation_path": str(external), "sha256": manager.sha256_file(external),
            }]}), encoding="utf-8")
            paths = {"home": root, "library": library, "manifest": manifest_path,
                     "state": root / "state", "catalog": root / "catalog.json", "settings": {}}
            with patch.object(manager, "config_paths", return_value=paths), patch.object(manager, "load_catalog", return_value=self._catalog()):
                with self.assertRaisesRegex(manager.ManagerError, "outside its catalog install target"):
                    manager.cmd_cleanup(Namespace(asset_id="safe-resource", apply=True, yes=True))
            self.assertEqual(external.read_text(encoding="utf-8"), "keep me")

    def test_repair_refuses_tampered_target_and_cache_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "library"
            target = library / "kdenlive/luts/safe.cube"
            target.parent.mkdir(parents=True)
            target.write_text("damaged", encoding="utf-8")
            external = root / "outside.cube"
            external.write_text("keep me", encoding="utf-8")
            paths = {"home": root, "library": library, "manifest": root / "installed.json",
                     "state": root / "state", "catalog": root / "catalog.json", "settings": {}}
            with patch.object(manager, "config_paths", return_value=paths), patch.object(manager, "load_catalog", return_value=self._catalog()):
                tampered_target = {"schema_version": 1, "resources": [{
                    "id": "safe-resource", "installation_path": str(external), "cache_path": str(external),
                    "sha256": manager.sha256_file(external),
                }]}
                manager.write_json_atomic(paths["manifest"], tampered_target)
                with self.assertRaisesRegex(manager.ManagerError, "outside its catalog install target"):
                    manager.cmd_repair(Namespace(asset_id="safe-resource", apply=True, yes=True))
                tampered_cache = {"schema_version": 1, "resources": [{
                    "id": "safe-resource", "installation_path": str(target), "cache_path": str(external),
                    "sha256": manager.sha256_file(external),
                }]}
                manager.write_json_atomic(paths["manifest"], tampered_cache)
                with self.assertRaisesRegex(manager.ManagerError, "outside this asset's manager cache"):
                    manager.cmd_repair(Namespace(asset_id="safe-resource", apply=True, yes=True))
            self.assertEqual(target.read_text(encoding="utf-8"), "damaged")
            self.assertEqual(external.read_text(encoding="utf-8"), "keep me")

    def test_verify_returns_failure_exit_code_for_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / "safe.cube"
            resource.write_text("LUT_3D_SIZE 2\n" + "0 0 0\n" * 8, encoding="utf-8")
            manifest_path = root / "installed.json"
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "safe-resource", "resource_type": "cube_lut", "installation_path": str(resource),
                "sha256": "wrong-hash",
            }]}), encoding="utf-8")
            paths = {"home": root, "library": root / "library", "manifest": manifest_path,
                     "state": root / "state", "catalog": root / "catalog.json", "settings": {}}
            output = StringIO()
            with patch.object(manager, "config_paths", return_value=paths), redirect_stdout(output):
                status = manager.main(["verify", "safe-resource", "--json"])
            self.assertEqual(status, 2)
            self.assertIn('"sha256": "failed"', output.getvalue())

    def test_verify_does_not_erase_application_runtime_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / "bundle.bundle"
            with zipfile.ZipFile(resource, "w") as bundle:
                bundle.writestr("paintoppresets/test.kpp", b"brush data")
            manifest_path = root / "installed.json"
            manifest_path.write_text(json.dumps({"schema_version": 1, "resources": [{
                "id": "safe-resource", "resource_type": "krita_bundle", "installation_path": str(resource),
                "sha256": manager.sha256_file(resource),
                "validation_results": {"application_runtime": {"status": "passed", "details": "Imported in Krita"}},
            }]}), encoding="utf-8")
            paths = {"home": root, "library": root / "library", "manifest": manifest_path,
                     "state": root / "state", "catalog": root / "catalog.json", "settings": {}}
            for options in ([], ["--app-smoke"]):
                with patch.object(manager, "config_paths", return_value=paths), redirect_stdout(StringIO()):
                    status = manager.main(["verify", "safe-resource", "--json", *options])
                saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(status, 0)
                self.assertEqual(saved["resources"][0]["validation_results"]["application_runtime"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
