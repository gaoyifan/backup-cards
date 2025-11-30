from pathlib import Path
import multiprocessing
import sys
from app import web_cmd, connect

def main():
    if len(sys.argv) == 4 and sys.argv[1] == "connect":
        connect(sys.argv[2], int(sys.argv[3]))
    elif len(sys.argv) == 1:
        db_path = Path.home() / ".local" / "share" / "sd-backup" / "sd-backup.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        web_cmd(
            db_path=db_path,
            web_host="127.0.0.1",
            web_port=0,
            web_public_url=None,
            with_webview=True)
    else:
        print("Invalid arguments")
        sys.exit(1)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()