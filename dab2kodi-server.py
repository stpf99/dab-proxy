#!/usr/bin/env python3
"""
dab2kodi-server.py
Serwuje playlist.m3u i epg.xml z katalogu ~/Muzyka/ przez HTTP.

Endpoints:
  GET /playlist.m3u  → plik M3U (dla Kodi / pvr.iptvsimple)
  GET /epg.xml       → plik XMLTV EPG
  GET /              → prosta strona statusu z linkami
"""

import argparse
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_DIR  = Path.home() / "Muzyka"


def file_mtime(path: Path) -> str:
    if path.exists():
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return "—"


def file_size(path: Path) -> str:
    if path.exists():
        kb = path.stat().st_size / 1024
        return f"{kb:.1f} KB"
    return "—"


class Handler(BaseHTTPRequestHandler):
    serve_dir: Path = DEFAULT_DIR

    # ── routing ──────────────────────────────────────────────────────────
    ROUTES = {
        "/playlist.m3u": ("playlist.m3u", "audio/x-mpegurl; charset=utf-8"),
        "/epg.xml":       ("epg.xml",      "application/xml; charset=utf-8"),
    }

    def do_GET(self):
        path = self.path.split("?")[0]   # ignoruj query string

        if path in self.ROUTES:
            filename, mime = self.ROUTES[path]
            self._serve_file(self.serve_dir / filename, mime)

        elif path in ("/", "/status"):
            self._serve_status()

        else:
            self._send_404()

    # ── helpers ──────────────────────────────────────────────────────────
    def _serve_file(self, filepath: Path, mime: str):
        if not filepath.exists():
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"Plik nie istnieje: {filepath}\n"
                f"Uruchom najpierw serwis dab2kodi.service aby wygenerować pliki.\n"
                .encode()
            )
            return

        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_status(self):
        host = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")
        base = f"http://{host}"

        m3u_path = self.serve_dir / "playlist.m3u"
        epg_path  = self.serve_dir / "epg.xml"

        html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>dab2kodi — status</title>
  <style>
    body  {{ font-family: monospace; background:#111; color:#eee; padding:2rem; }}
    h1    {{ color:#4fc; }}
    a     {{ color:#4af; }}
    table {{ border-collapse:collapse; margin-top:1rem; }}
    td,th {{ padding:.4rem 1.2rem; border:1px solid #444; }}
    th    {{ color:#4fc; text-align:left; }}
    .ok   {{ color:#4f4; }}
    .miss {{ color:#f44; }}
  </style>
</head>
<body>
  <h1>📻 dab2kodi HTTP server</h1>
  <table>
    <tr><th>Plik</th><th>URL</th><th>Rozmiar</th><th>Ostatnia zmiana</th><th>Status</th></tr>
    <tr>
      <td>playlist.m3u</td>
      <td><a href="{base}/playlist.m3u">{base}/playlist.m3u</a></td>
      <td>{file_size(m3u_path)}</td>
      <td>{file_mtime(m3u_path)}</td>
      <td class="{'ok' if m3u_path.exists() else 'miss'}">{'✓ OK' if m3u_path.exists() else '✗ brak'}</td>
    </tr>
    <tr>
      <td>epg.xml</td>
      <td><a href="{base}/epg.xml">{base}/epg.xml</a></td>
      <td>{file_size(epg_path)}</td>
      <td>{file_mtime(epg_path)}</td>
      <td class="{'ok' if epg_path.exists() else 'miss'}">{'✓ OK' if epg_path.exists() else '✗ brak'}</td>
    </tr>
  </table>
  <p style="margin-top:2rem;color:#888;">
    Katalog: {self.serve_dir}<br>
    Wygenerowano: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
  </p>
  <hr style="border-color:#333">
  <p style="color:#888;font-size:.85rem;">
    Konfiguracja Kodi — pvr.iptvsimple:<br>
    &nbsp;&nbsp;M3U&nbsp; → <code>{base}/playlist.m3u</code><br>
    &nbsp;&nbsp;XMLTV → <code>{base}/epg.xml</code>
  </p>
</body>
</html>"""

        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_404(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"404 Not Found\n")

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} — {fmt % args}",
              flush=True)


def main():
    parser = argparse.ArgumentParser(description="dab2kodi HTTP server (M3U + EPG)")
    parser.add_argument("--port",    type=int, default=DEFAULT_PORT,
                        help=f"Port HTTP (domyślnie: {DEFAULT_PORT})")
    parser.add_argument("--serve-dir", default=str(DEFAULT_DIR),
                        help=f"Katalog z plikami M3U i XML (domyślnie: {DEFAULT_DIR})")
    parser.add_argument("--host",   default="0.0.0.0",
                        help="Adres nasłuchu (domyślnie: 0.0.0.0 — wszystkie interfejsy)")
    args = parser.parse_args()

    Handler.serve_dir = Path(args.serve_dir).expanduser().resolve()

    print(f"[dab2kodi-server] Katalog: {Handler.serve_dir}")
    print(f"[dab2kodi-server] Nasłuchuję na http://{args.host}:{args.port}/")
    print(f"[dab2kodi-server] M3U  → http://localhost:{args.port}/playlist.m3u")
    print(f"[dab2kodi-server] EPG  → http://localhost:{args.port}/epg.xml")
    print(f"[dab2kodi-server] Info → http://localhost:{args.port}/")

    server = HTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dab2kodi-server] Zatrzymano.")
        sys.exit(0)


if __name__ == "__main__":
    main()
