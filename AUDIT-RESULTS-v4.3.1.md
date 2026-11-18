# WoSB Workbench v4.3.1 — pre-install recovery audit fixes

**This is the audited/revised v4.3.1 source package.** It supersedes the earlier v4.3.1 startup-hotfix ZIP for anyone who has not installed it yet. The product version remains **4.3.1**; it is not a separately installed release.

## Evidence reviewed

- `WoSB-Full-Analysis-20261117-132805.zip`, extracted from two locally installed clients.
- Original `ModelTextureLinks.jsonl` containing 63,764 records from the user's scan.
- `WoSB-Ship-Model-Debug-Samples3.zip` containing eight original model XNB examples.
- The complete v4.3.1 startup-hotfix source and its tests.

The two client scans each report 2,482 XNB-named files: 830 successfully decoded model assets, 1,545 successfully decoded textures, 75 failed assets, and 32 unsupported EffectReader assets.

### Reclassified/repairable failures

| Existing report, per client | Files | Audited change | Status until local recheck |
|---|---:|---|---|
| `ValueError: XNB is not a Texture2D asset` | 71 | Root `SpriteFontReader` was misclassified by an included **nested** `Texture2DReader`. A font-atlas decoder now attempts to export the embedded texture. | Synthetic test passed; original game font files still require Windows validation. Glyph layout data is not reconstructed. |
| `MeshDecodeError: Unsupported shared-resource layout (1, 2, 0)` | 2 | Zero is a valid absent optional effect reference. Allow it while keeping vertex/index validation. | Synthetic model-buffer test passed; the original `wtframe` files were not included in the upload. |
| `XNBError: Not a complete XNB header` | 2 | Record as unrecognized binary formats instead of corrupt Texture2D/Model assets, with header evidence. | Still unsupported; actual format not identified. |
| EffectReader bodies unsupported | 32 | Attempt to preserve validated compiled-effect bytes as `.fxb` *for research*, leaving their status unsupported. | Original shader source, bindings and fidelity are still not recovered; original effect files were not uploaded. |

### Material linkage: the misleading 32,124 number

The previous 63,764-record link file reported **31,640 candidate filename matches** and **32,124 unresolved labels**. Within those unresolved labels:

- **31,882** were the generic `Texture` slot name, not actual named texture files.
- **242** were specific labels, confined in this dataset to terrain/sky/environment resources.
- **6,308** of the generic placeholder records were associated with ship models; there were **no unresolved specific ship material names** in this scan.

The new link stage ignores generic placeholders and reports them separately. A filename match is still **not** a verification of shader accuracy or a guarantee that any design renders correctly.

### Code coverage correction

The previous game scan hit the default cap of **350,000 methods**, so its code index was incomplete even though the code phase could finish. v4.3.1 now prioritizes game-specific assemblies, records the method-limit condition and identifies the unvisited assembly count. This does **not** recover missing server-side gameplay formulas; an increased method limit and controlled experimental recordings are still required for complete investigation.

### Performance and preservation

The audit revision reuses **unchanged successful model and texture outputs** from the known v4.0/v4.1 reader revisions if their source sizes and modification times still match and saved outputs exist. Previously failed or unsupported content is retried. Pass `--recheck` for a full read of every source file if desired.

The included **`Recheck-Decoders-Only.cmd`** performs an asset/relink/review pass without redoing the full catalog and 350,000-method code index. It uses the Python `.build-venv` created by `Build-Windows.cmd` and the existing `%LOCALAPPDATA%\WoSBWorkbench\FullRecovery-AllClients` workspace. Additional installation paths can be supplied as `--game "D:\Your\Game"` arguments.

## Validation

- The complete existing regression suite plus seven new recovery-audit tests passes.
- All eight uploaded source XNB model examples still parse to their full original triangle counts.
- The extracted recovery evidence and the original package passed ZIP integrity checks.
- Live rendering, game-supplied SpriteFont atlases, shader extraction, the Windows installer and original `wtframe` reconstruction **have not been tested on Windows**.

## Limitations

No exact server-authoritative cannon damage or vulnerability heatmaps were recovered from these failure diagnostics. Shader bytecode preservation is not shader reverse-engineering. The two unknown binary file types still require original bytes for format identification. The 242 environment texture labels may use separate lookup rules.
