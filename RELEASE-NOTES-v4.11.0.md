# WoSB Workbench 4.11.0: the wiki in 15 languages

- **Every page is available in 14 more languages**, alongside English:
  Chinese, Hindi, Spanish, Arabic, French, Bengali, Portuguese, Russian, Indonesian, Urdu, German, Japanese, Turkish
  and Korean. Each lives at its own address, for example `wosbwiki.org/es/port/port-nevis.html`.
- **Language picker with flags** in the top bar, next to the search box, on desktop and phones.
- Pages are translated by Cloudflare Workers AI the first time someone opens them, then remembered. Text shared by all
  pages (menus, footer, headings, table headers) is translated once per language, and a new publish only translates
  new or changed text.
- Arabic and Urdu read right to left. Each language page has its own canonical address.
- Every English page lists its language versions (`hreflang`) for search engines.
- The privacy policy explains that only page text is sent for translation.
- Setup is in `docs/WOSBWIKI-HOSTING.md`: add a Workers AI binding `AI` and a KV binding `TRANSLATIONS` to the Pages
  project. Without them the language pages show English.
