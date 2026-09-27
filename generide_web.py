#!/usr/bin/env python3
"""Start generide's web UI on this machine and open it in the browser.

Usage:
    python generide_web.py
    python generide_web.py --port 8800 --no-browser

The page sets up Mine Train requests, shows runs live, checks results in the
headless game, installs them, and keeps every run in a library for rerunning
and comparing. See the README's "Use the web UI" section, and rct2/webui.py
for how the server works.

It only listens on 127.0.0.1, so nothing else on the network can reach it.
Runs started from the page keep going if this server is stopped; start it
again to pick them back up.
"""

import argparse
import sys
import webbrowser

from rct2 import runrecord
from rct2.webui import make_server

DEFAULT_PORT = 8765


def main():
    parser = argparse.ArgumentParser(description="Start generide's local web UI")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on, on 127.0.0.1 only (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the address instead of opening it in the browser",
    )
    args = parser.parse_args()

    try:
        server, app = make_server(args.port)
    except OSError as exc:
        print(f"Error: could not listen on port {args.port}: {exc.strerror}. "
              f"Is generide's web UI already running? Try --port.", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{app.port}/"
    print(f"generide web UI: {url}")
    print(f"Run library: {runrecord.library_root()}")
    print("Press Ctrl-C to stop the server. Runs already going keep going.")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped the web UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
