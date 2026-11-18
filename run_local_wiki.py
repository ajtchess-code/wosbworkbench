"""Open the local WoSB Codex using the user's saved catalog or bundled starter data."""
from threading import Event
from workbench_db import home, bundled_path
from wiki_server import serve

def main():
    db=home()/'Workbench.sqlite3'
    if not db.is_file():db=bundled_path('Starter-Catalog.sqlite3')
    server,address=serve(db,port=0,open_browser=True)
    print('WoSB Codex running locally at '+address,flush=True)
    print('Press Ctrl+C to close the wiki server.',flush=True)
    try:Event().wait()
    except KeyboardInterrupt:server.shutdown();server.server_close()

if __name__=='__main__':main()
