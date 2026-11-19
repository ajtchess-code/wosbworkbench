# WoSB Workbench 4.5.2

## Fixed
- **"SQLite objects created in a thread can only be used in that same thread"** when building the wiki website
  or the battle & boarding simulators. Both jobs now open their own database connection in the background.
  A test now catches any background job that reuses the main window's connection.
