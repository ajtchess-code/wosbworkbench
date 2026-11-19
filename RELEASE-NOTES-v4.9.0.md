# WoSB Workbench 4.9.0: login, reports, icons and Title Case

## Discord login, report forms and an admin dashboard
- **Log in with Discord** from the top bar on every page of wosbwiki.org. Only the `identify` scope (name and avatar)
  is used, and logging in is optional.
- **Report a problem with this page** at the bottom of every page, and **Tell us** links in the footer, on the main
  page and on the About page. Both open the same form: kind (wrong / missing / suggestion / other), details and an
  optional contact. Anonymous senders pass Cloudflare Turnstile; logged-in users skip it.
- **Admin dashboard** at `/admin/`, only for the Discord accounts in `ADMIN_DISCORD_IDS`. Admins can see every report,
  filter by Open / Resolved / Won't fix, search, add notes, delete, and download CSV.
- Everything runs in the site's Cloudflare Pages Function (`_worker.js`), and reports are stored in Cloudflare D1:
  - signed HttpOnly login cookies;
  - checks against other sites sending requests;
  - per-hour limits on reports;
  - IP addresses stored only as one-way hashes.
- The privacy policy and terms of use now cover login, reports, Turnstile and analytics.
- The setup steps are in `docs/WOSBWIKI-HOSTING.md`. Until the settings are added, the buttons stay hidden.

## Pictures and models
- Item pages show the game's own icon for cannons, ammunition, upgrades, crew, captain skills, resources, cosmetics
  and island decorations. Icons also appear in category tables and folded entries.
- Ship pages show the ship's art.
- Cosmetics without an icon use a thumbnail of their own texture.
- Cannon and mortar pages have a **3D model** viewer. It loads only when you press "Show 3D model". The weapons
  models are now part of the wiki's model pack.

## Tracking and ads
- Google Tag Manager container `GTM-TMZFVXTL` is on every page (setting `wiki.gtm_id`).
- The AdSense code (`ca-pub-6442579332215350`) is on every page except the full-screen simulators, the admin page and
  the 404 page.

## Title Case
- Menus, page titles, headings, table headers, the search index and short link text now use Title Case, for example
  "Captain Skills" and "Ports and Port Battles". Game item and ship names keep the game's spelling.
- Cannon infoboxes read in plain words: "Medium Cast Iron", "Bought with gold", "Speed factor ×1.25".
