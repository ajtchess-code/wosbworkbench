# WoSB Workbench 4.12.2

- **Language pages fixed for Worker deploys**: every publish now includes `wrangler.jsonc` and `.assetsignore`, so a site hosted as a Cloudflare Worker (not a Pages project) runs the wiki's worker: translations, Discord login, reports and the model pack. Settings `wiki.worker_name`, `wiki.kv_id`, `wiki.d1_id`.
- **Translations never block the page**: a language page is sent at once with what is already translated; the rest is translated in the background. Extensionless URLs and `/es` without a slash work.
- **Icons**: lanterns and figureheads (cut from the game's icon sheet), title medals in bronze / silver / gold, achievement pictures, and 34 consumables.
- **Achievement pages** show their title medal at each level; the Captain Titles page shows every medal.
- **Sails compared**: a side-by-side table with a column per stat. **Consumables**: a compare table per group and a repair-value table (durability per minute of cooldown and per material).
- **3D ship viewer**: a "Damage heatmap" on/off checkbox; choosing a skin, sail cloth, flag, figurehead or pattern switches the heatmap and hull box off so the design shows.
