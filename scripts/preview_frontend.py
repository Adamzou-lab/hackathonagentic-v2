"""Aperçu local avec CSS actualisé à l'enregistrement, sans backend ni clé API.

Lancement depuis le dépôt : python3 scripts/preview_frontend.py
Puis ouvrir http://127.0.0.1:8782/?demo
"""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def revision():
    stamps = {"css": [], "page": []}
    for path in sorted(STATIC.rglob("*")):
        if path.is_file():
            stat = path.stat()
            group = "css" if path.name == "styles.css" else "page"
            stamps[group].append(f"{path.relative_to(STATIC)}:{stat.st_mtime_ns}:{stat.st_size}")
    return {key: hashlib.sha256("\n".join(value).encode()).hexdigest()
            for key, value in stamps.items()}


def live_reload():
    return """<script>
(() => {
  let current = CURRENT_REVISION;
  async function refresh() {
    try {
      const response = await fetch('/__preview/revision', {cache: 'no-store'});
      if (!response.ok) return;
      const next = await response.json();
      if (next.page !== current.page) {
        location.reload();
        return;
      }
      if (next.css !== current.css) {
        const old = document.querySelector('link[rel="stylesheet"][href^="/static/styles.css"]');
        if (old) {
          await new Promise((resolve, reject) => {
            const fresh = old.cloneNode();
            fresh.href = '/static/styles.css?v=' + next.css;
            fresh.onload = () => { old.remove(); resolve(); };
            fresh.onerror = () => { fresh.remove(); reject(new Error('CSS indisponible')); };
            old.after(fresh);
          });
        }
        current = next;
      }
    } catch (_) {
      // Une sauvegarde ou un redémarrage peut rendre un fichier indisponible un instant.
    } finally {
      setTimeout(refresh, 700);
    }
  }
  setTimeout(refresh, 700);
})();
</script>""".replace("CURRENT_REVISION", json.dumps(revision()))


class PreviewHandler(BaseHTTPRequestHandler):
    def send_content(self, content, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/__preview/revision":
            self.send_content(json.dumps(revision()).encode(), "application/json")
            return
        if url.path in ("/", "/index.html"):
            if "demo" not in parse_qs(url.query, keep_blank_values=True):
                self.send_response(302)
                self.send_header("Location", "/?demo")
                self.end_headers()
                return
            markup = (STATIC / "index.html").read_text()
            markup = markup.replace("</body>", live_reload() + "\n</body>")
            self.send_content(markup.encode(), "text/html; charset=utf-8")
            return
        if url.path.startswith("/static/"):
            relative = Path(unquote(url.path[len("/static/"):]))
            path = (STATIC / relative).resolve()
            if (STATIC in path.parents and path.is_file()
                    and not any(part.startswith(".") for part in relative.parts)):
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_content(path.read_bytes(), mime)
                return
        self.send_content(b"Not found", "text/plain", 404)

    def log_message(self, format, *args):
        if args and args[1] != "200":
            super().log_message(format, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8782)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"Aperçu direct : http://127.0.0.1:{args.port}/?demo", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
