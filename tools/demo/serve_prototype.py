"""Local, read-only prototype preview. Exposes only the HTML and browser map config."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


class PreviewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/prototype-next.html"):
            body = (ROOT / "prototype-next.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif path == "/api/maps/config":
            try:
                with urlopen("http://127.0.0.1:18080/api/maps/config", timeout=4) as response:
                    body = response.read()
            except Exception:
                self.send_error(503, "Local map configuration unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            self.send_error(404)
            return
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 5175), PreviewHandler).serve_forever()
