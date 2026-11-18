# WoSB Workbench v3.7 — Network Research Lab

- New sidebar Network Research Lab, local PCAP and PCAPNG import with progress, flow summaries, protocol classification, binary framing hints, UTC event markers and ±5s temporal correlations.
- Optional passive packet recording via TShark and Npcap on a selected interface. Explicit consent and manual stop; no packet injection.
- Separate network_sessions and network_events SQLite tables, preserving existing wiki edits and imports.
- One-click evidence-to-wiki article and redacted JSON research export. Exports exclude original PCAP, full IP addresses, authentication payloads, and capture file paths.
- Defensive capture parser: bounds, multiple formats, VLAN, TCP/UDP, IPv4/IPv6, common PCAPNG timestamp resolutions.
- Supported limit: ~2GB file, 2 million packets. No TCP reassembly, no automatic attribution to the game process, and no encrypted message decoding.
- Source tests: 38 passing (including six network-specific tests). Windows EXE must be compiled on Windows via Build-Update.cmd.

### Privacy

Packet captures may contain sensitive material. Original packets remain locally stored in files and are NEVER included in Workbench research JSON exports. Exported event notes are user-authored; review them before sharing.

### Remaining work

Protocol reverse engineering needs actual, authorized local capture samples and controlled experiments; no claims that specific WoSB gameplay message formats have been decoded.
