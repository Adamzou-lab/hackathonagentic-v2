import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from scripts.build_netlify import build


def test_only_configured_origin_can_read_authenticated_api(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCKIN_ALLOWED_ORIGINS', 'https://lockin-demo.netlify.app')
    token = 'deployment-test-' + 'x' * 32
    app = create_app(db_path=str(tmp_path/'db'), access_token=token)
    with TestClient(app) as client:
        origin = {'Origin':'https://lockin-demo.netlify.app'}
        preflight = client.options('/api/missions', headers=origin | {
            'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'authorization,content-type,last-event-id'})
        assert preflight.status_code == 200
        assert preflight.headers['access-control-allow-origin'] == origin['Origin']
        denied = client.get('/api/watches', headers=origin)
        assert denied.status_code == 401
        response = client.get('/api/watches', headers=origin | {'Authorization':'Bearer '+token})
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        alien = client.options('/api/missions', headers={
            'Origin':'https://untrusted.example', 'Access-Control-Request-Method':'POST'})
        assert alien.status_code == 400
        assert 'access-control-allow-origin' not in alien.headers


def test_netlify_artifact_is_real_and_contains_only_public_configuration(tmp_path):
    output = build('https://adamzou.fr/lockin-api', tmp_path/'site')
    assert 'https://adamzou.fr/lockin-api' in (output/'index.html').read_text()
    assert not (output/'demo-mode.js').exists()
    markup = (output/'index.html').read_text()
    assert '<style id="lockin-styles">' in markup
    assert (output/'static/styles.css').read_text() in markup
    assert '<link rel="stylesheet"' not in markup
    assert json.loads((output/'version.json').read_text())['mode'] == 'real'
    assert all(p.name not in {'.env', 'operator-token.txt'} for p in output.rglob('*'))


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:secret@example.com',
                               'https://example.com?token=secret'])
def test_build_rejects_credentials_in_public_url(tmp_path, url):
    with pytest.raises(ValueError):
        build(url, tmp_path/'site')
