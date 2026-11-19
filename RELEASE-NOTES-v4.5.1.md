# WoSB Workbench 4.5.1

## New
- **Game audio**:
  - Full Recovery now decodes the game's sound effects to WAV files, with codec, length, channels and
    loop points recorded.
  - `Reports/Audio-Inventory.csv` lists every sound by group (effects, environment, UI, voices,
    soundtrack…) and cue name.
- **Plain-text assets**: files that carry an .xnb name but are plain text (credits and link tables, such as
  authors and SailNormalsLinking) are saved as readable .txt files instead of being reported as unknown binaries.
- **Wiki: Missions & NPCs**. Every PvE mission has its own page, wave by wave (pirates, reinforced pirates,
  traders, named bosses), and there is a list of every kind of NPC ship.
- **Incremental Full Recovery for code**: the code index is reused when the game's assemblies haven't changed.
  Asset decoding was already incremental.
- **CI wiki preview**: every build makes a wiki from the bundled starter catalog and attaches it as a
  downloadable artifact, so broken wiki pages are caught before a release.

## Fixed
- Sound effects were classified as **shaders**: the reader name "SoundEffectReader" contains "EffectReader".
  Some of the "unsupported shaders" in past recovery reports were sounds.

## Note
- The next Full Recovery re-exports models once so they include gun ports and hardpoints. Textures are reused,
  so the run is shorter than the first one.
