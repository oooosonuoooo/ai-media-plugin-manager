# Resource integration and verification

Use the application-native resource path for each type. Catalog status and file hash checks are not substitutes for opening the editor and using a resource.

## Krita

- The normal Linux resource directory is `~/.local/share/krita`; use the configured location shown by Krita's Resource Manager if it differs.
- Import `.bundle` files from the manager's central library through **Settings → Manage Resource Libraries → Import**. Preserve the original bundle and verify it appears in the bundle/resource list. Restart Krita when the resource type requires it.
- Verify the expected brushes, patterns, gradients, or templates in their dockers. A valid ZIP alone is only archive validation.
- Install Python plugins only after reviewing the source and dependencies. Krita plugins can access user files. Use **Tools → Scripts → Import Python Plugin…**, enable it in **Configure Krita → Python Plugins Manager**, restart, then run a harmless sample action.
- Krita 5 includes G'MIC integration in supported builds. Check the in-app Filter menu before installing a separate G'MIC package.

## Kdenlive

- The Linux user title-template folder is `~/.local/share/kdenlive/titles`. Use `.kdenlivetitle` files and verify the template list in the Title Editor.
- LUTs can live in an organized shared folder. Apply them with the **Apply LUT** effect and select the exact file. Keep camera/log technical transforms separate from creative looks; apply a technical LUT only to matching footage.
- Kdenlive 26.08 supports JSON (Lottie) animations and Glaxnimate `.rawr` files with alpha. Install manager-cataloged JSON into the shared motion-graphics library, then import the chosen file into the project bin and check it on a short timeline render. `media-assets verify <id> --app-smoke` runs a bounded, one-thread MLT render, checks alpha at a mid-frame, and fully decodes the result. This verifies the renderer path, not the project-bin GUI workflow. To create or edit an animation from the project bin, configure Glaxnimate in Kdenlive's settings; see the [official animation documentation](https://docs.kdenlive.org/en/project_and_asset_management/project_bin/animation.html).
- Verify an effect in Kdenlive's Effects panel and render a short synthetic or disposable sample. FFmpeg support for a filter does not prove Kdenlive exposes or serializes it correctly.
- Check audio plugin visibility in Kdenlive's Audio Effects panel after installation. A LADSPA or LV2 library being present on disk does not prove Kdenlive can use it.

## Local AI Media Studio

- Inspect `media_health` and `media-assets doctor` before render or model tasks. The doctor makes a read-only, bounded request to ComfyUI's local queue API; `busy` means defer work that could compete for GPU resources. Recheck immediately before starting because queue state can change. Respect the configured GPU free-memory threshold and do not interrupt an active render or ComfyUI queue.
- Keep Studio outputs and project media under its configured workspace, and never modify source footage in place.
- For tasks requiring a new resource, search the local catalog first, then continue the original task after installation and validation.

## Status fields

- `discovered`: a source was found and recorded.
- `downloaded`: a file was fetched to quarantine/staging but not activated.
- `installed`: the file is in the target resource location.
- `verified`: the application loaded and used it successfully in a recorded smoke test.
- `failed`: a check was attempted and failed, with evidence recorded.
- `deferred`: it may be useful, but a known reason prevents installation now.
- `unsupported`: incompatible, legally restricted, or outside the supported install mechanism.
