"""Start the tracker: python -m app [--port 8000] [--no-browser]"""
import argparse
import threading
import webbrowser

import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--no-browser", action="store_true")
args = parser.parse_args()

url = f"http://127.0.0.1:{args.port}"
if not args.no_browser:
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
print(f"D&D Collection Tracker running at {url}  (Ctrl+C to stop)")
uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
