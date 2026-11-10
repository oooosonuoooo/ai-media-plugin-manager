---
name: ai-media-plugin-manager
description: Finds, checks, installs, updates, and validates free creative resources for Krita, Kdenlive, and a local AI Media Studio. Use when an image, illustration, animation, or video task needs reusable brushes, effects, templates, LUTs, plugins, or media assets.
---

# AI Media Plugin Manager

Use this skill before a creative task when a missing resource could materially improve the result.

## Workflow

1. Identify the task's needed capability and supported formats.
2. Run `media-assets search "<capability>"` to check manager-installed records, the machine-local indexed inventory, files in the creative library, and catalog candidates. Use `media-assets list` for editor resource locations. Reuse a verified match after checking its validation and license. A path-only file still needs provenance and compatibility review.
3. Search official application resources and maintainer sources before broader community sources. Search online with `media-assets search "<capability>" --online` when the local catalog is insufficient.
4. Check the individual asset's license, commercial-use terms, attribution, source, version, file hash, editor compatibility, dependencies, and size. A repository license does not automatically cover every asset in it.
5. Install only a catalog item marked installable with verified license and compatibility. The CLI refuses unreviewed items, insecure URLs, unsafe file types, hash mismatches, and overwrites by default.
6. Ask for approval before using an unclear license, running third-party code, making destructive changes, or using privileged access outside the user's stated setup authorization. Do not run downloaded scripts to install resources.
7. Verify the installed file and its application behavior. A download, archive check, or matching hash alone is not proof that the editor loaded the resource.
8. Continue the original creative task and record the resource path and any attribution requirement.

## Commands

Run `media-assets --help` first. The CLI is standard-library Python and provides:

- `media-assets search <query> [--online]`
- `media-assets install <id>`
- `media-assets list`
- `media-assets update [id]`
- `media-assets verify [id] [--app-smoke]`
- `media-assets repair <id>`
- `media-assets catalog`
- `media-assets cleanup [id]`

Install and update commands request confirmation unless `--yes` is supplied. Cleanup is a dry run unless `--apply --yes` is supplied. Never use those flags to bypass an unresolved license, compatibility, or security question.

The optional `MEDIA_ASSET_INDEX` file defaults to `~/.local/share/ai-media-plugin-manager/local-inventory.json` and uses a top-level `resources` list. It records already-installed files the manager does not own, including their provenance, license, paths, hashes, compatibility, and test evidence. `search`, `list`, and `verify` read this inventory; a missing hash is reported as not recorded, and a missing file is reported as missing. Indexed resources are excluded from `update`, `repair`, and `cleanup`; only the manager's own install manifest is eligible for those operations.

## Resource-specific notes

- For Krita bundles, use the native Resource Manager import flow and restart Krita when required. Read [Krita resource integration](references/resource-integration.md) before installing bundles or Python plugins.
- For Kdenlive title templates, use the documented user titles directory. LUTs are file-based: select the installed `.cube` in Kdenlive's Apply LUT effect, and treat technical camera transforms separately from creative looks.
- For vector motion graphics, search for pinned `lottie_json` entries. The manager rejects expression strings and external image paths, stores the JSON and required notices in the shared motion-graphics library, and can run `media-assets verify <id> --app-smoke` through the MLT producer. Import the exact file into Kdenlive's project bin and render a sample before claiming GUI use is verified; read [Kdenlive animation integration](references/resource-integration.md).
- Use `media-assets list` and the local configuration to identify the active workspace and resource library. Do not assume or recreate a retired workspace path.
- Check local GPU availability before starting model inference or rendering. Avoid concurrent GPU-heavy work and respect the configured free-space floor.
- Keep downloaded third-party assets out of this source repository unless their license explicitly permits redistribution. Store machine-specific inventory and install records outside the repository.

## Status vocabulary

Use `discovered`, `downloaded`, `installed`, `verified`, `failed`, `deferred`, and `unsupported` precisely. Mark a resource `verified` only after the relevant application-level check passes. Record any limitation, such as camera-specific LUT input requirements, unmet VRAM, or a license that allows manual use but forbids AI derivation.
