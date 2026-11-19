# WoSB Workbench 4.8.1

- **Publish wiki to wosbwiki.org no longer needs Git.** If Git isn't installed, Workbench uploads the site straight to
  GitHub with an access token, using Git's own upload protocol. Make a fine-grained token limited to the wiki
  repository, with "Contents: Read and write". It is stored encrypted for your Windows account and asked for again only
  if GitHub rejects it.
- If Git is installed, it is found even when Workbench was opened before Git was added to PATH.
- The wiki repository defaults to `https://github.com/ajtchess-code/wosbwiki.git`.
