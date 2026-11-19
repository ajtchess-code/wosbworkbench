# Hosting the WoSB Wiki at wosbwiki.org (Cloudflare Pages)

Workbench builds the whole wiki as static files. Cloudflare Pages serves them from a **private** GitHub repository,
and Cloudflare's network sits in front for HTTPS, caching and bot protection. There is no server to run.

```
Workbench ── Build wiki website ──► WikiSite/ ── Publish wiki to wosbwiki.org ──► private GitHub repo (main)
                                                                                      │ (auto-deploy)
                                                                                      ▼
                                                          Cloudflare Pages ──► https://wosbwiki.org
```

The build already contains everything the host needs:

| File | What it does |
|---|---|
| `_headers` | Blocks framing by other sites, forces HTTPS (HSTS), turns off MIME sniffing, and sets strict referrer and permissions policies. Data files get a same-site resource policy, so other sites can't hotlink them. |
| `_redirects` | Permanent redirects from folded or merged pages to their new address. |
| `_worker.js` + `_routes.json` | Runs only for `/pack/*`, the 3D models. It refuses requests that don't come from the wiki's own pages. |
| `ads.txt`, `robots.txt`, `sitemap.xml` | Lines for AdSense and search engines. `robots.txt` also blocks the known AI-training crawlers. |
| `404.html` | The not-found page. |
| `privacy.html`, `terms.html`, `disclaimer.html` | Privacy policy, terms of use and copyright disclaimer. |

## One-time setup

1. **Domain.** Register `wosbwiki.org` (Cloudflare Registrar is simplest), or add it to Cloudflare and point the
   registrar's nameservers at the ones Cloudflare gives you.
2. **Private repository.** On GitHub, create an empty **private** repository, for example `ajtchess-code/wosbwiki-site`.
   It must be private. A public repository would let anyone download the whole site and its model pack in one click.
3. **First publish.** In Workbench, run **Build wiki website**, then **Publish wiki to wosbwiki.org** and paste the
   repository URL. Each publish replaces the branch with a single snapshot commit, so the repository stays small.
4. **Pages project.** In Cloudflare go to Workers & Pages → Create → Pages → Connect to Git, and choose the repository.
   - Production branch: `main`
   - Framework preset: *None*
   - Build command: *(empty)*
   - Build output directory: `/`
5. **Custom domain.** In the Pages project, go to Custom domains and add `wosbwiki.org` and `www.wosbwiki.org`. Then add a
   Redirect Rule (Rules → Redirect Rules) that sends `www.wosbwiki.org/*` to `https://wosbwiki.org/${1}` with a 301.
6. **Contact email.** Use Email → Email Routing to forward `contact@wosbwiki.org` to an inbox you read. The legal pages
   give this address, which you can change with the `wiki.contact_email` setting.

## Cloudflare security settings

These are the dashboard settings that stop scraping and abuse. All of them are on the free plan.

- **SSL/TLS**
  - Encryption mode: *Full (strict)*.
  - Edge Certificates: *Always Use HTTPS* on, *Automatic HTTPS Rewrites* on, *Minimum TLS* 1.2, *TLS 1.3* on.
- **Security → Bots**
  - Turn on *Bot Fight Mode*.
  - Turn on *Block AI bots*, under AI Crawl Control or Bots depending on the dashboard version.
- **Security → Settings**
  - Security level *Medium*.
  - *Browser Integrity Check* on.
- **Security → WAF → Custom rules** (5 free). Add a rule "Block site downloaders" with action **Block** and this expression:
  ```
  (http.user_agent contains "HTTrack") or (http.user_agent contains "Wget") or (http.user_agent contains "WebCopier")
  or (http.user_agent contains "WebZIP") or (http.user_agent contains "Teleport") or (http.user_agent contains "Offline Explorer")
  or (http.user_agent contains "SiteSnagger") or (http.user_agent contains "WebReaper") or (http.user_agent contains "Scrapy")
  or (lower(http.user_agent) contains "python-requests") or (http.user_agent contains "curl/") or (http.user_agent eq "")
  ```
- **Security → WAF → Rate limiting rules** (1 free). Match all URIs (`http.request.uri.path wildcard "/*"`), 60 requests
  per 10 seconds per IP, action *Block* for 10 seconds. That is plenty for a reader, but stops a mirroring tool.
- **Scrape Shield**
  - *Hotlink Protection* on, so other sites can't embed the wiki's images.
  - *Email Address Obfuscation* on.

A public website can always be read, so it can also be copied by hand. These settings, the headers and the model-pack
guard stop framing, hotlinking, bulk downloaders and AI scrapers. The terms of use make copying and mirroring a breach
of the site's rules.

## Google AdSense and Search Console

1. In AdSense → Sites, add `wosbwiki.org`. Every page already carries the `google-adsense-account` meta tag, and the
   site has `ads.txt`.
2. Turn on **Auto ads**. The ad script is only on pages with real content. Utility pages such as the simulators, recent
   changes and the 404 page are ad-free and kept out of search.
3. In **Privacy & messaging**, create a *European regulations* message (EEA, UK and Switzerland) and a *US state
   regulations* message. The privacy policy already describes both.
4. In Google Search Console, add `wosbwiki.org` as a domain property and submit `https://wosbwiki.org/sitemap.xml`.

## Moving off bandofmisfits.org

Once wosbwiki.org is live, set `PUBLIC_WIKI_REDIRECT=https://wosbwiki.org` on the BOM dashboard host and restart it.
Wiki pages on bandofmisfits.org and wiki.bandofmisfits.org then answer with a 301 to the same path on wosbwiki.org, and
bandofmisfits.org's home page is the guild landing page again.

The Discord commands (`/ship`, `/damage`, `/fire`, `/tower`, `/wosb`) read the last wiki release uploaded to the
dashboard. If none is uploaded, they read `https://wosbwiki.org/assets/hit-data.js`. If Bot Fight Mode ever challenges
the bot host, keep using **Publish wiki to Band of Misfits** as well, so the bot always has local data.

## Workbench settings

| Setting | Default | Used for |
|---|---|---|
| `wiki.site_url` | `https://wosbwiki.org/` | Canonical links, sitemap, social cards |
| `wiki.cloudflare_remote` | asked on first publish | Private GitHub repository Cloudflare deploys from |
| `wiki.ad_client` | `ca-pub-6442579332215350` | AdSense publisher ID (`ads.txt`, ad script) |
| `wiki.donate_url` | `https://paypal.me/litefootz` | Donate button |
| `wiki.discord_url` | *(none)* | "Join our Discord" link and contact line |
| `wiki.contact_email` | `contact@wosbwiki.org` | Contact address on the legal pages |
| `wiki.standalone` | `true` | Ads, donate footer and Cloudflare files in the build. Set it to `false` only to host on the BOM dashboard, which then adds its own bar. |
