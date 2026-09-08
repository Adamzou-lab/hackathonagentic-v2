import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import MissionInput
from app.storage import Store, TERMINAL, StorageUnavailable
from app.stream import Broker, mission_stream
from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider


def create_app(*, db_path=None, access_token=None, provider=None, incident_path=None):
    token = os.getenv('LOCKIN_ACCESS_TOKEN', '') if access_token is None else access_token
    key = os.getenv('ANTHROPIC_API_KEY', '')
    configured = provider is not None or bool(key)

    @asynccontextmanager
    async def lifespan(app):
        store = Store(db_path or os.getenv('LOCKIN_DB_PATH', 'data/lockin.db'),
                      incident_path=incident_path or os.getenv('LOCKIN_INCIDENT_PATH') or None)
        store.recover()
        broker = Broker()
        app.state.store = store
        app.state.broker = broker
        app.state.provider = provider or AnthropicProvider(
            key, os.getenv('LOCKIN_MODEL','claude-haiku-4-5'), broker=broker)
        app.state.engine = Engine(store, app.state.provider)
        try:
            yield
        finally:
            await app.state.engine.close()
            store.db.close()

    app = FastAPI(title='Lockin', version='0.1.0', lifespan=lifespan)

    @app.exception_handler(StorageUnavailable)
    async def storage_unavailable(request, exc):
        # Le stockage possède son journal de secours indépendant de SQLite.
        # Aucune réponse ne prétend que l'arrêt a été enregistré dans la base.
        return JSONResponse({'detail':exc.code, 'dependency':'sqlite', 'reaction':'stop'},
                            status_code=503)

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
        app.state.store.check_available()
        if app.state.engine.unconfirmed_stops:
            raise HTTPException(503, 'cancellation_unconfirmed')
        return {'status':'ok', 'service':'Lockin'}

    @app.get('/api/config', dependencies=[Depends(authorize)])
    async def config():
        return {'provider_ready':configured, 'max_domains':5, 'max_actions':100,
                'max_duration_minutes':30, 'poll_interval_ms':1000}

    @app.get('/api/incidents', dependencies=[Depends(authorize)])
    async def incidents():
        """Secours consultable même quand le journal principal est indisponible."""
        return app.state.store.incidents()

    @app.post('/api/missions', status_code=202, dependencies=[Depends(authorize)])
    async def create(request: MissionInput):
        app.state.store.check_available()
        if (app.state.engine.closing or app.state.engine.storage_failed or
                app.state.engine.unconfirmed_stops):
            raise HTTPException(503, 'Agent arrêté ; intervention opérateur requise.')
        existing = app.state.store.reusable(request)
        if existing:
            state = snapshot(existing)
            state['reuse'] = {'reason': 'recent_completed' if state['status'] == 'completed' else 'already_running',
                             'window_hours': 24}
            return JSONResponse(state, status_code=200)
        if request.watch_id:
            try:
                app.state.store.watch(request.watch_id)
            except KeyError:
                raise HTTPException(404, 'Veille introuvable.')
        if not configured:
            raise HTTPException(503, 'ANTHROPIC_API_KEY manquante côté serveur.')
        if app.state.engine.active():
            raise HTTPException(409, 'Une mission est déjà en cours.')
        target = request.watch_id or app.state.store.exact_watch(request)
        if not target and not request.allow_new:
            candidates = app.state.store.similar_watches(request)
            if candidates:
                raise HTTPException(409, {'code':'similar_watches', 'candidates':candidates})
        mid = app.state.store.create(request, watch_id=target)
        # Une seule mission tourne a la fois : le rattachement des fragments
        # provisoires est donc non ambigu.
        bind = getattr(app.state.provider, 'bind', None)
        if callable(bind):
            bind(mid)
        app.state.engine.launch(mid)
        return snapshot(mid)

    @app.get('/api/watches', dependencies=[Depends(authorize)])
    async def watches(query: str = Query(default='', max_length=500),
                      limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return app.state.store.list_watches(query, limit, offset)

    @app.get('/api/watches/{wid}', dependencies=[Depends(authorize)])
    async def watch(wid: str):
        try:
            return app.state.store.watch(wid)
        except KeyError:
            raise HTTPException(404, 'Veille introuvable.')

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

    @app.get('/api/missions/{mid}/stream', dependencies=[Depends(authorize)])
    async def stream(mid: str, last_event_id: str = Header(default='')):
        """Flux SSE authentifie. Lecture seule : ne lance jamais de mission.

        Une reconnexion reprend au `Last-Event-ID` fourni, donc sans doublon et
        sans relancer quoi que ce soit.
        """
        snapshot(mid)
        try:
            resume = int(last_event_id)
        except (TypeError, ValueError):
            resume = 0
        generator = mission_stream(app.state.store, app.state.broker, mid,
                                   last_seq=max(0, resume), terminal=TERMINAL)
        return StreamingResponse(generator, media_type='text/event-stream', headers={
            'Cache-Control': 'no-store',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        })

    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=str(static), check_dir=False), name='static')

    @app.get('/', include_in_schema=False)
    async def home():
        index = static / 'index.html'
        return FileResponse(index) if index.is_file() else RedirectResponse('/docs')

    return app


app = create_app()
