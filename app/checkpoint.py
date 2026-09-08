"""Serveur de recette : désactive explicitement un outil dans ce processus."""
import argparse
from contextlib import asynccontextmanager
import os
from pathlib import Path

from app.main import create_app
from start import read_config

TOOLS = ('search_web', 'read_page', 'save_finding')


def failure_app(tool):
    if tool not in TOOLS:
        raise ValueError('Outil de test inconnu')
    app = create_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original_lifespan(instance):
            instance.state.engine.disabled_tools = frozenset({tool})
            yield

    app.router.lifespan_context = lifespan
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disable-tool', required=True, choices=TOOLS)
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port invalide')
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    for key, value in read_config(root / '.env').items():
        if key in {'ANTHROPIC_API_KEY','LOCKIN_MODEL','LOCKIN_ACCESS_TOKEN'}:
            os.environ.setdefault(key, value)
    # Ne jamais utiliser la base de l'instance normale pour provoquer une panne.
    os.environ['LOCKIN_DB_PATH'] = str(root / 'data' / 'checkpoint.db')
    print(f'TEST : {args.disable_tool} désactivé sur http://127.0.0.1:{args.port}/', flush=True)
    print('Le modèle reste réel et consomme du crédit. Ctrl+C quitte ce mode.', flush=True)
    import uvicorn
    uvicorn.run(failure_app(args.disable_tool), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
