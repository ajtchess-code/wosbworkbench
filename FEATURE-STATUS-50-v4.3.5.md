# Requested 50 improvements — implementation/evidence status

Status definitions: **New** = implemented as a new source feature and locally
unit-tested; **Existing** = already in the latest v4.3.4 baseline and retained;
**Partial** = a useful implementation exists but full original-game correctness
is not established; **Requires live validation** = cannot certify without the
real Windows client, gameplay observation, authoritative game data or a GPU.
No entry below claims an exact WoSB server formula or shader match.

| # | Improvement | Status | Evidence / current limitation |
|---|---|---|---|
| 1 | Intelligent asset failure recovery | Partial | `advanced_assets.recovery_triage` classifies and queues; underlying unsupported reader still requires implementation and original bytes |
| 2 | Complete mesh triangle validation | Partial | `model_quality` + XNB index/bone checks; need original Apostolov reference comparison |
| 3 | Automatic vertex-format identification | New | `engine/xnb_geometry.describe_vertex_declaration`; unknown formats flagged |
| 4 | Model hierarchy reconstruction | Existing | XNB bone transforms in `engine/xnb_geometry`; other XNB layouts can fail explicitly |
| 5 | Cross-client asset comparison | New | SHA-256 inventory/diffs in `advanced_assets` |
| 6 | Original material-binding reconstruction | Partial | Material candidate bindings and shader status already present; shader runtime mapping unverified |
| 7 | Shader/effect reconstruction | Partial | v4.3.4 compiled effect audit retained; exact runtime behavior is not decoded |
| 8 | Fully functional ship designs | Requires live validation | v4.3.3 sidecar texture loaders and design warnings retained; actual in-game parity unverified |
| 9 | Advanced texture reconstruction | Existing / partial | Texture2D decoding, PNG and material handling; proprietary shaders and blend effects remain unknown |
| 10 | Original appearance validation | Existing | `visual_reference.compare_screenshots`; user must supply aligned screenshots |
| 11 | Collision geometry discovery | Partial | Candidate helpers and catalog hitbox fields; source server collision use not proven |
| 12 | 3D hitbox visualization | Existing / partial | Evidence-gated zones in browser ship viewer; no guaranteed authoritative hitbox |
| 13 | Triangle-accurate impact detection | New | `advanced_geometry.MeshRaycaster` BVH + intersection point, normal, component |
| 14 | Armor thickness/angle mapping | Partial | Geometric angle and user-supplied uniform armor; no recovered local thickness map |
| 15 | Component-specific impact zones | Partial | Rendered mesh categories and named candidate helpers; actual damage mapping unknown |
| 16 | Weapon behavior profiles | Existing | Catalog-based cannon/mortar/weapon research and provisional models |
| 17 | Ammunition simulation | Existing / partial | Catalog ammo factors in ballistics/damage tools; server effects not confirmed |
| 18 | Penetration and ricochet | Partial | Two deliberately competing damage hypotheses; ricochet formula not verified |
| 19 | Dynamic damage heatmaps | New / experimental | `advanced_geometry.sample_heatmap` user-defined uniform armor, NOT real weak spots |
| 20 | Predicted vs observed damage | New / experimental | `advanced_experiments` plus `damage_hypotheses`; indices not misrepresented as HP |
| 21 | Capture readiness test | Existing | v4.3.2 interface, port traffic preflight and packet checks retained; live verification needed |
| 22 | TCP stream reassembly | New / bounded | `advanced_network` continuity, retransmit/overlap/gap tracking; no protocol message decryption |
| 23 | Protocol message classification | Partial | Framing/binary family hints only; unverified game message type semantics |
| 24 | Multi-target identity tracking | New / evidence-gated | Explicit source tokens hashed to stable IDs; ambiguous events intentionally unassigned |
| 25 | Subsecond event synchronization | New | Affine fit from user-paired capture/video clock anchors |
| 26 | Guided experiment wizard | Partial | Advanced Research structured HP trial form plus existing Combat Evidence workflow; full multi-step guided wizard not yet implemented |
| 27 | Automatic combat event detection | Partial | `advanced_video` visual transients; cannot classify firing/hits reliably from pixel difference |
| 28 | Health-change extraction | Existing / partial | v4.3 baseline HP video measurement tool; human verification required |
| 29 | Combat evidence database | New | `advanced_experiments` SQLite with explicit provenance |
| 30 | Scientific experiment comparison | New | Config-matched means, variance and approximate CIs; trial independence must be verified |
| 31 | Wind performance simulator | New / experimental | `advanced_sailing.compare_wind_profiles` recovered component and custom coefficients |
| 32 | Sail configuration analysis | New / experimental | `advanced_ship_config.sail_condition_observations`; observational association only |
| 33 | Turning/maneuverability | New | `advanced_sailing.evaluate_maneuver` from measured positions and times |
| 34 | Projectile trajectory sandbox | New / experimental | `advanced_sailing.trajectory` classical ballistic toy model |
| 35 | Comparative sailing laboratory | New / experimental | Parametric side-by-side wind profiles, not asserted real ship speeds |
| 36 | Gun-port reconstruction | Partial | `advanced_ship_config.mount_candidates` identifies candidate named groups; real slot count unknown |
| 37 | Production-chain explorer | Existing + New | Existing `engine.recipe_chains` plus `advanced_catalog.crafting_graph` |
| 38 | Ship configuration simulator | Existing + New | Existing loadout research plus user-defined `outfit_hypothesis`; server stacking unknown |
| 39 | Asset-linked encyclopedia | Existing | Local wiki/catalog, model/image data and provenance retained |
| 40 | Version-to-version data comparison | New | `advanced_catalog.compare_catalogs` hashes dataset records |
| 41 | Unified 3D scene inspector | Existing | Ship viewer group counts, visibility, materials, picks; more shader telemetry still needed |
| 42 | Recovery coverage dashboard | Existing | `research_suite.asset_coverage`, Full Recovery status and Discovery Center |
| 43 | Confidence and provenance | Existing + New | Source/status labels added to new reports, original evidence gating retained |
| 44 | Long-operation management | Existing / partial | Existing Full Recovery resume/checkpoint/cancel; new CLI analysis bounded but not all GUI tasks support pause |
| 45 | Portable research exports | New | `advanced_experiments.export_experiments`, SHA-256 manifests and existing review exports |
| 46 | Regression coverage | New | 25 added tests and 105 existing baseline tests; 130 passed locally on Python 3.13 |
| 47 | Clean Windows installation | Requires live validation | Windows scripts updated but no actual frozen Windows build executed here |
| 48 | Performance profiling | New / partial | Synthetic CPU geometry benchmark; not GPU render FPS or sustained capture throughput |
| 49 | Crash recovery and integrity | Existing + New | Prior recovery checkpoints + `advanced_io` atomic report writes; full power-loss tests pending |
| 50 | Automated release verification | New / partial | Source manifest, hashes, syntax checks, ZIP integrity; Windows, actual game and shaders not certified |

**Release recommendation:** Do not label all 50 items fully completed. The newly
added workflows are testable source features, but critical rendering, collision,
server formulas and live Windows setup still require evidence and tests.
