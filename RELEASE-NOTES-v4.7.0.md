# WoSB Workbench 4.7.0 — the WoSB Wiki

The built website is now the **WoSB Wiki**, ready to launch on bandofmisfits.org.

## Branding
- New original logo: a gold ship's-wheel emblem with a sailboat on a navy sea, plus a "WoSB WIKI" wordmark (`viewer/brand`).
- Favicons: `favicon.ico` (16/32/48), SVG favicon, Apple touch icon, 192/512 PNG app icons and `site.webmanifest`.
- 1200×630 social card for Discord, Facebook and X link previews.

## Search engines and sharing (`site_seo.py`)
- Every page gets a meta description, canonical URL, Open Graph and Twitter tags, theme colour and icon links.
- JSON-LD WebSite and Organization data on the main page.
- `sitemap.xml` with every indexable page, and `robots.txt` pointing to it (packs disallowed).
- Pages with very little text are marked `noindex`. The BOM host shows no ads on them, which keeps the site in line with Google AdSense rules on low-value content.
- New setting `wiki.site_url` (default `https://bandofmisfits.org/`) sets the canonical address.

## Content
- New main page with feature cards for the big tools.
- New About page, a Privacy & cookies page (AdSense cookies, Google ad settings, EEA/UK consent) and an All pages index.
- Cosmetic pages explain each design slot. Resource pages list what makes them, what uses them, and where they trade. Port pages describe their port type.
- Fixed breadcrumbs on mission and guide pages.
