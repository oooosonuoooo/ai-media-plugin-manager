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
mkdir -p "$HOME/.local/bin" "$HOME/.codex/skills" "$HOME/.gemini/config/skills"
ln -s "$(pwd)/scripts/media-assets" "$HOME/.local/bin/media-assets"
python3 scripts/install_skill.py install
```

Add `$HOME/.local/bin` to `PATH` if it is not already there. The installer links the skill into Codex's user skill folder and Antigravity IDE's documented global folder, `~/.gemini/config/skills/`, and refuses to replace a real directory or a link pointing elsewhere. See [Google Antigravity's skill documentation](https://antigravity.google/docs/skills) for workspace and global discovery rules.

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

Online search returns GitHub repository metadata only. It does not establish the license of individual files or make a result installable. Add an asset to the installable catalog only after reviewing its exact license, provenance, compatibility, file type, size, source pin, and install target.

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
