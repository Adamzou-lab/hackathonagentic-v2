"""Lanceur local multiplateforme : python3 start.py (Windows : py start.py)."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import tempfile
import urllib.request
import venv
import warnings
import webbrowser

ROOT = Path(__file__).resolve().parent


def write_private(path, content):
    """Crée le fichier avec des droits privés avant d'y écrire un secret."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".lockin-secret-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_config(path):
    config = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and not name.startswith("#"):
                config[name.strip()] = value.strip().strip("\"'")
    return config


def main():
    parser = argparse.ArgumentParser(description="Installer et lancer Lockin localement.")
    parser.add_argument("--demo", action="store_true", help="Aperçu simulé sans clé API")
    parser.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.exit(1, "Python 3.12 minimum est nécessaire : https://www.python.org/downloads/\n")
    if not 1 <= args.port <= 65535:
        parser.error("Le port doit être compris entre 1 et 65535.")

    os.chdir(ROOT)
    path = ROOT / ".env"
    config = read_config(path)
    updates = {}
    key = os.environ.get("ANTHROPIC_API_KEY") or config.get("ANTHROPIC_API_KEY", "")
    if not args.demo and (not key or "REMPLACER" in key):
        print("Clé API Anthropic requise pour une vraie recherche (saisie masquée).")
        # Refuser une saisie visible si le terminal ne permet pas le masquage.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                key = getpass.getpass("Clé Anthropic : ").strip()
            except getpass.GetPassWarning:
                parser.exit(1, "Ouvrez un terminal interactif pour saisir la clé de façon masquée.\n")
        if not key or "\n" in key or "\r" in key:
            parser.exit(1, "Clé vide ou invalide. Pour un aperçu sans clé : ajouter --demo.\n")
        updates["ANTHROPIC_API_KEY"] = key
    token = os.environ.get("LOCKIN_ACCESS_TOKEN") or config.get("LOCKIN_ACCESS_TOKEN", "")
    if len(token) < 32 or "REMPLACER" in token:
        token = secrets.token_hex(32)
        updates["LOCKIN_ACCESS_TOKEN"] = token
    if not path.exists():
        write_private(path, "# Configuration locale Lockin — ne pas publier.\n")
    if updates:
        # Conserve les autres paramètres et remplace uniquement les valeurs demandées.
        lines = path.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if line.strip().partition("=")[0].strip() not in updates]
        lines.extend(f"{name}={value}" for name, value in updates.items())
        write_private(path, "\n".join(lines) + "\n")
    if os.name != "nt":
        path.chmod(0o600)
    token_dir = ROOT / ".lockin"
    token_dir.mkdir(mode=0o700, exist_ok=True)
    write_private(token_dir / "operator-token.txt", token + "\n")

    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("1/3 — Création de l’environnement Python…", flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    print("2/3 — Installation des dépendances…", flush=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"], check=True)
    env = {**os.environ, **read_config(path)}
    env["LOCKIN_ACCESS_TOKEN"] = token
    if key:
        env["ANTHROPIC_API_KEY"] = key
    url = f"http://127.0.0.1:{args.port}/" + ("?demo" if args.demo else "")
    print(f"3/3 — Démarrage : {url}", flush=True)
    if not args.demo:
        print("Dans l’interface, collez le jeton du fichier .lockin/operator-token.txt (aucune clé API dans ce fichier).", flush=True)
    print("Gardez ce terminal ouvert. Ctrl+C pour arrêter.", flush=True)

    def open_when_ready():
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return
            except OSError:
                threading.Event().wait(0.5)

    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    subprocess.run([str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)], env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nLockin arrêté.")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Démarrage impossible : {exc}. Vérifiez Python, Internet et le port disponible.", file=sys.stderr)
        sys.exit(1)
