"""Paquet frontend réel : aucune clé ni jeton, uniquement l'URL HTTPS publique."""
import argparse
import html
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit


def build(api_base, output):
    root = Path(__file__).resolve().parents[1]
    url = urlsplit(api_base)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or
            url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError('Une URL HTTPS publique sans identifiants ni paramètres est requise.')
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(root / 'app/static', destination / 'static')
    markup = (root / 'app/static/index.html').read_text()
    placeholder = '<meta name="lockin-api-base" content="" />'
    if markup.count(placeholder) != 1:
        raise ValueError('Configuration frontend manquante ou ambiguë.')
    markup = markup.replace(placeholder,
        '<meta name="lockin-api-base" content="' + html.escape(api_base.rstrip('/'), quote=True) + '" />')
    (destination / 'index.html').write_text(markup)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    (destination / 'version.json').write_text(json.dumps({'commit':commit, 'mode':'real', 'api_base':api_base.rstrip('/')}))
    (destination / '_headers').write_text('/*\n  Cache-Control: no-store\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.api_base, args.output))
