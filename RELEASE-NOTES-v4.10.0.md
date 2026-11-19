# WoSB Workbench 4.10.0: ports, the world map and plain wording

## Port pages
Every port has a full page again, built from the game's own world data:
- Faction (for example Port Nevis is a **Kai & Severia** port), produced resource, shipyard size and port-battle team
  size.
- Special features: starting port, Samurai / Musketeer / Fisher crews, northern ice, Arab port, pirates only,
  stronghold, no battle window.
- A **map of the surrounding waters**, with towers, imperial forts, resource nodes, trade routes and shallow-water
  tint.
- **Waters:** the largest ship that can reach the port, worked out from the game's shallow-water map.
- Defences (towers by type and nearby forts), **trade routes** that start or end at the port, resources nearby, and
  neighbouring ports with distances.

## World map
- Port names show at every zoom (toggle "Port names").
- **Trade routes are typed and coloured the way the game types them** (Main, Supply, Coastal, Central, Smuggling),
  can be filtered by type, and are clickable. Each route shows its ends, cargo, length and the largest ship that can
  sail it.
- New **Shallow waters** layer showing where ships above a given rank can't sail, with a legend.
- Port popups show faction, produce, shipyard and waters. Resource nodes are named (Iron mine · Iron Ore, and so on).
- `map.html?route=N` opens a route. A trade-route table and a shallow-water explainer are below the map.

## Wording
- Pages no longer talk about how the data is gathered: no "game client", datamining, scans or Workbench steps. A
  final pass over every page catches older guide text too.
