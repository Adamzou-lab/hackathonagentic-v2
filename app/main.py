import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import MissionInput
from app.storage import Store
from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider


def create_app(*, db_path=None, access_token=None, provider=None):
    token = os.getenv('LOCKIN_ACCESS_TOKEN', '') if access_token is None else access_token
    key = os.getenv('ANTHROPIC_API_KEY', '')
    configured = provider is not None or bool(key)

    @asynccontextmanager
    async def lifespan(app):
        store = Store(db_path or os.getenv('LOCKIN_DB_PATH', 'data/lockin.db'))
        store.recover()
        app.state.store = store
        app.state.engine = Engine(store, provider or AnthropicProvider(key, os.getenv('LOCKIN_MODEL','claude-haiku-4-5')))
        try:
            yield
        finally:
            await app.state.engine.close()
            store.db.close()

    app = FastAPI(title='Lockin', version='0.1.0', lifespan=lifespan)

    def authorize(authorization: str = Header(default='')):
        if len(token) < 32:
            raise HTTPException(503, 'LOCKIN_ACCESS_TOKEN doit contenir au moins 32 caractères.')
        if not secrets.compare_digest(authorization.encode(), ('Bearer '+token).encode()):
            raise HTTPException(401, 'Jeton opérateur requis.', headers={'WWW-Authenticate':'Bearer'})

    def snapshot(mid):
        try:
            return app.state.store.snapshot(mid)
        except KeyError:
            raise HTTPException(404, 'Mission introuvable.')

    @app.get('/health')
    async def health():
        return {'status':'ok', 'service':'Lockin'}

    @app.get('/api/config', dependencies=[Depends(authorize)])
    async def config():
        return {'provider_ready':configured, 'max_domains':5, 'max_actions':100,
                'max_duration_minutes':30, 'poll_interval_ms':1000}

    @app.post('/api/missions', status_code=202, dependencies=[Depends(authorize)])
    async def create(request: MissionInput):
        if not configured:
            raise HTTPException(503, 'ANTHROPIC_API_KEY manquante côté serveur.')
        if app.state.engine.active():
            raise HTTPException(409, 'Une mission est déjà en cours.')
        mid = app.state.store.create(request)
        app.state.engine.launch(mid)
        return snapshot(mid)

    @app.get('/api/missions/{mid}', dependencies=[Depends(authorize)])
    async def get(mid: str):
        return snapshot(mid)

    @app.post('/api/missions/{mid}/stop', dependencies=[Depends(authorize)])
    async def stop(mid: str):
        snapshot(mid)
        app.state.engine.stop(mid)
        return snapshot(mid)

    @app.get('/api/missions/{mid}/events', dependencies=[Depends(authorize)])
    async def events(mid: str):
        snapshot(mid)
        return app.state.store.events(mid)

    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=str(static), check_dir=False), name='static')

    @app.get('/', include_in_schema=False)
    async def home():
        index = static / 'index.html'
        return FileResponse(index) if index.is_file() else RedirectResponse('/docs')

    return app


app = create_app()
