#!/usr/bin/env python3
"""Serve the built site locally, the way GitHub Pages serves it.

Module workers and WebAssembly need exact content types, and Python's
built-in server guesses them from the platform's MIME tables, which differ
between machines (CI runs Python 3.9). This pins the ones the page needs.

Usage: python demo/tools/serve.py [--port 8777] [--dir _site]
"""

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".zip": "application/zip",
    ".svg": "image/svg+xml",
}


class Handler(SimpleHTTPRequestHandler):
    extensions_map = dict(SimpleHTTPRequestHandler.extensions_map, **TYPES)

    def log_message(self, format, *args):  # quiet, test output stays readable
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parents[2] / "_site")
    args = parser.parse_args()
    handler = functools.partial(Handler, directory=str(args.dir))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
