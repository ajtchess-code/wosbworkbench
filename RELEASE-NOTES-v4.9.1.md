# WoSB Workbench 4.9.1

- **Fixed: after a publish, pages could appear unstyled until the browser's saved copy expired.** Every stylesheet and
  script link now carries a version tag (`site.css?v=…`) that changes whenever the file changes, so visitors always get
  the files that match the page.
- Images and other files in `assets/` are now saved by browsers for an hour (was a day) and rechecked after that.
