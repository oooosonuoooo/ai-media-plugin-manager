# AI Media Plugin Manager

An open-source, conservative resource catalog and installer for Krita, Kdenlive, and local AI media workflows. It checks the local catalog first, records provenance and hashes, refuses unclear or incompatible resources, and keeps downloaded third-party assets outside this source repository.

## Requirements

- Python 3.10 or newer
- Linux for the current automatic install targets
- FFmpeg for the optional `.cube` smoke check
- GitHub API access only for `search --online`; no token is required for public repository search

The manager uses Python's standard library and does not run downloaded code. Installable catalog entries are static assets only.

## Install locally

Clone the repository, then install the command and skill in user-level directories:

```sh
python3 scripts/install_skill.py install
python3 scripts/install_skill.py verify
```

The installer manages the `media-assets` command at `~/.local/bin/media-assets`, the Codex user skill, and Antigravity IDE's documented global skill folder, `~/.gemini/config/skills/`. It refuses to replace a real directory or a link pointing elsewhere. Use `repair` only when you want it to replace conflicting symbolic links; it still preserves real directories. `uninstall` removes only links that resolve to this checkout. Add `$HOME/.local/bin` to `PATH` if it is not already there. See [Google Antigravity's skill documentation](https://antigravity.google/docs/skills) for workspace and global discovery rules.

Limit installation to a target with `--scope cli`, `--scope codex`, or `--scope antigravity`. `--scope both` manages the two skill links, while the default `--scope all` manages all three targets.

Optionally set a local library root in `~/.config/ai-media-plugin-manager/config.json`:

```json
{
  "library_root": "/path/to/your/AI-Media-Studio/Assets/Creative"
}
```

This file is machine-specific and should not be committed. Environment variables `MEDIA_ASSET_LIBRARY`, `MEDIA_ASSET_MANIFEST`, `MEDIA_ASSET_STATE`, and `MEDIA_ASSET_CATALOG` override the corresponding paths.

## Use

```sh
media-assets --help
media-assets list
media-assets search "cinematic LUT"
media-assets search "Krita watercolor brush" --online
media-assets catalog
media-assets install <catalog-id>
media-assets verify <catalog-id> --app-smoke
media-assets update
media-assets repair <catalog-id>
media-assets cleanup
```

Search shows matching installed records, other files found by path in the configured creative library, and catalog candidates. Use `--json` for the same groups in a machine-readable result. Review provenance and compatibility before using a file found only by path.

Online search adds GitHub repository metadata. Review the exact license, provenance, compatibility, file type, size, source pin, and install target before making an asset installable.

The default install flow asks for confirmation. `cleanup` is a dry run unless both `--apply` and `--yes` are supplied. Updating backs up the previous manager-owned file before replacing it. Existing unrelated files are never overwritten or deleted.

## Catalog and provenance

`manifests/catalog.json` is a source catalog with `discovered`, `deferred`, and `unsupported` records. Each local installation is recorded outside the repository in the user's XDG data directory. The install record stores the name, version, author, source, license, commercial use, attribution, SHA-256, installation path, compatible applications, tested versions, installation time, update state, and validation outcomes.

The manager distinguishes published checksums from hashes calculated after an HTTPS download. A calculated hash is useful for deduplication and later integrity checks, but it is not presented as an upstream checksum. Archive validation does not prove that an editor imported or can use the resource; record a separate application-level test before marking an item `verified`.

## Current workstation notes

This project was developed against Krita 5.3.4.1, Kdenlive 26.08.2, MLT 7.42, and FFmpeg 9.0.2. The source repository deliberately does not include user configurations, project media, downloaded resources, local install manifests, credentials, or machine-specific audit reports. The active AI Video Studio can be connected through a local config file without changing its MCP setup.

## Maintenance and safety

- Refresh the catalog manually when a task needs a capability; no background scans or automatic upgrades run.
- Search installed resources before fetching new files.
- Use HTTPS sources and immutable source commits for raw GitHub files.
- Verify each license at the asset level. A package's code license may differ from the art, model, font, or media it downloads.
- Do not run remote scripts or install executable plugins through this static-asset installer.
- Keep a recoverable configuration checkpoint before changing Krita or Kdenlive resources.
- Read [resource integration notes](references/resource-integration.md) for application-specific import and testing steps, and [checkpoint recovery](references/checkpoint-restore.md) before changing an editor profile.

## Development checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/doctor.py
```

When available, validate the skill folder with the Codex `skill-creator` utility (`quick_validate.py <path-to-this-skill>`).

CI runs the standard-library test suite. The skill is intentionally conservative: candidates with unclear rights, unsupported formats, large size, or untested code remain deferred or unsupported.
