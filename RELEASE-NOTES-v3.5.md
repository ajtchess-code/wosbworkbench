# WoSB Workbench v3.5 — Model Forensics + Full Research Import

## Proven results from user-supplied reports and original XNB sample

- On the original `Ship_62_Vasa.xnb` (SHA-256 `ac892c5186354a2d7c12cb28ffad604e32c813f82ad89886d5345d5e26a550c0`), a read-only CAB-compatible LZX decoder **successfully produced 5,004,353 bytes**, from 153 frames plus five zero-padding bytes.
- XNB model parser found **27 type readers, 95 shared resources, 40 bone records, and 39 declared meshes**. The first mesh is named `1_SailAnimated1`.
- The sample contains custom `UWModelMeshPartTag`, `SegmentTextureInfoTag`, `UWModelTag`, and other readers. **Complete vertex/index geometry, accurate mesh reconstruction, and collision/damage overlays remain unverified.**
- The full 76 MB recent research ZIP imports cleanly with the updated importer: 13,560 source records processed, preserving 84 ship records in each of Game and Steam builds. It audits all three scans and produces 73 research findings. Audit results are not proof of entire-game completeness.

## New features

- Bounded XNB LZX CAB reconstruction with native decoder selection (Windows `expand.exe`, optional `7z`/libarchive fallback; libarchive confirmed on Linux with the user sample).
- Ignores only verified alignment padding after the final frame, rather than misclassifying zero padding as corruption. Reports actual Windows decoder errors if decompression fails.
- `engine/xnb_model_probe.py`: reads type reader list, first mesh metadata, and model bones with bounds checks; operates on raw XNB or user-exported sample ZIP. No client assemblies executed.
- Ship 3D: select Game/Steam build, browse all indexed ship XNB candidates regardless of ship-name match, manually link a candidate to a selected ship as *unverified research*, inspect any XNB/sample ZIP, and export manually selected XNB samples.
- Local model candidate associations saved under `%LOCALAPPDATA%\WoSBWorkbench\Models\candidate_links.json`, independent of application updates.
- Skips redundant `Catalog-2`, `Catalog-3`, and later duplicate catalogs when the canonical catalog exists, preventing expensive repeat imports.
- Source-linked Vasa research wiki entry with explicit confidence limits.

## Existing capabilities retained

Editable local wiki, catalog, Discovery Center audits, combat research, sailing and wind, crafting economy, source provenance, reports, offline verified updater, portable Windows app and installer builder.

## Critical limits

- No automatic OBJ or GLB output for XNB models yet. The custom reflective readers and mesh buffers must be decoded before this is accurate.
- `Ship_62_Vasa.xnb` is user-provided proprietary game content; the release contains *only provenance metadata and research results*, **not** raw copyrighted XNB game assets.
- CAB decompression is verified with libarchive in a Linux test environment. Windows `expand.exe` needs validation on the intended Windows installation; the GUI creates actionable error reports.
- The source ZIP is not a compiled updater ZIP. Run the Windows build script to create `dist\WoSBWorkbench-3.5.0-Update.zip` with `wosb-update.json`, matching hashes and compiled EXE payload.

## Windows build/update

1. Extract source ZIP and open `WoSB-Workbench-v3.5`.
2. Run `Build-Update.cmd` (requires Python 3.13; build process installs other Python dependencies into `.build-venv`, and uses installed Inno Setup 6 for a normal installer).
3. Inside Workbench v3.4, open **Updates → Choose update ZIP** and select `dist\WoSBWorkbench-3.5.0-Update.zip` from the new build.
4. Back up your wiki first; the updater preserves `%LOCALAPPDATA%\WoSBWorkbench` and its imported data.

Tested: 27 source tests and a real sample LZX/model-metadata extraction. **Windows EXE and updater must be built and verified on Windows.**
