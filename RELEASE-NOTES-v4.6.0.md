# WoSB Workbench 4.6.0

## Publish to Band of Misfits
- New action: **Publish wiki to Band of Misfits**. It uploads the built wiki to bandofmisfits.org in checked ZIP parts (each under 40 MB, with SHA-256 checks), and the site switches to the new release only once every part has arrived.
- It uses an upload token created in the dashboard (Wiki → Officer Tools → Compendium). The token is remembered after the first publish.

## Shipyard
- The Ships page opens with the in-game shipyard layout: faction bands (Antilia, Español, Kai & Severia, Empire, Premium and unique), the game's row order, gold and silver stars, premium badges, ship art and hover stats.
- The game's own shipyard background is used when a Full Recovery has it.

## Interactive world map
- The world map is now the game's own map texture (Data/Textures/map.png). It is matched to the client's world coordinates using the island placements: u = Position1 / 22700 + 0.5, v = 0.495 − Position0 / 18800.
- It shows the 42 world ports under their real names (linked through the client's `nport_N` map parameters), plus port type, the highest rate the port can build, and flags. It also shows port-battle sites named after their nearest port, towers, imperial forts, villages and lighthouses, resource nodes, altars and the 105 trade routes.
- Drag, scroll or pinch to zoom; layers toggle on and off; ports are searchable, and `map.html?port=Name` opens on a port. Port names appear as you zoom in.

## Fixes
- City-level factors for tower strength in the defenses data were shifted by one level.
