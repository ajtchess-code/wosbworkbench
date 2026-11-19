# WoSB Workbench 4.8.0: the WoSB Wiki on its own site

The wiki now builds as a stand-alone site for **wosbwiki.org**, hosted on Cloudflare Pages. The setup guide is
`docs/WOSBWIKI-HOSTING.md`.

## Hosting and security
- New action **Publish wiki to wosbwiki.org**. It pushes the build to a private GitHub repository as a single snapshot
  commit, and Cloudflare Pages deploys from there.
- Each build includes Cloudflare files:
  - `_headers`: no framing by other sites, HSTS, nosniff, strict referrer and permissions policies, and same-site data files.
  - `_redirects`: old page addresses lead to their new place.
  - `ads.txt` and `404.html`.
- A small Pages Function guards the 3D model pack. It answers only requests from the wiki's own pages, so the models
  can't be hotlinked or bulk-downloaded.
- `robots.txt` blocks AI-training crawlers. Search engines and the AdSense crawler are still allowed.
- Pages refuse to run inside another site's frame.
- The guide lists the Cloudflare dashboard settings to turn on: bot protection, a block on site downloaders, rate
  limiting and hotlink protection.
- AdSense Auto ads, the donate button and the Discord link are built in. Ads appear only on pages with real content.

## Legal pages
- New **Privacy policy** covering Cloudflare, Google AdSense cookies, EEA/UK consent, US state opt-outs, local storage
  and children.
- New **Terms of use**: no mirroring, scraping, AI training or framing.
- New **Copyright disclaimer**: World of Sea Battle and all of its imagery, 3D models, textures, designs, names and
  data belong to Thera Interactive, and this is an unofficial fan site. It also gives rights holders a way to ask for
  material to be removed.
- Every page footer carries the ownership notice and links to all three pages.

## Less clutter
- Thin pages are folded into their category page as anchored entries: a skill, an achievement, a decoration, a port,
  or a cosmetic with a few facts. Text shared by many pages is shown once, under "About …". On the test build this cut
  1,008 pages to about 200, all of them with real content.
- The 34 short in-game help pages are merged into six topic guides:
  - Ships, guns and consumables
  - Ports and port battles
  - Guilds and factions
  - Trading, crafting and making money
  - PvP, flags and notoriety
  - The world, adventures and NPC ships
- The boarding, sailing and wind, and damage calibration help pages are merged into the matching mechanics pages.
- Every old address redirects to the new one, and links, search, the sitemap and the data files are all updated.
- Placeholder records named "Removed" are no longer published.

## Phones and tablets
- On phones the menu slides in from the left, and the header has a sticky search box.
- Wide tables scroll sideways instead of stretching the page.
- Touch targets are larger, and inputs are sized so phones don't zoom in on them.
- Layouts are tuned for tablets. No page scrolls sideways at 390, 820 or 1280 px wide.

## Fixes
- Article tables of contents were always empty. They now list the page's sections.
- Effect names no longer show a stray "C" ("Workshop level +1", not "CWorkshop level +1").
- Cosmetic kinds and bonuses read in plain words ("Paint", "Reduce damage to nose").
