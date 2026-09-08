# Frontend Netlify et backend persistant

Le frontend public contient uniquement l'URL HTTPS du backend. Le jeton opérateur
reste saisi dans la page ; la clé Anthropic existe uniquement dans
`/etc/lockin/lockin.env` sur le VPS. Aucun secret n'entre dans le paquet Netlify.

Le backend utilise le service `deploy/lockin.service`, un seul worker sur
127.0.0.1:8018 et les chemins persistants `/var/lib/lockin` et `/var/log/lockin`.
Le fragment Nginx `lockin-nginx.conf` s'insère dans le serveur existant adamzou.fr.
Il expose `/lockin-api/` via le HTTPS déjà disponible sur ce domaine. Nginx ne
bufferise ni ne met en cache le streaming. Les autres sites sont conservés.

Configuration serveur : ANTHROPIC_API_KEY, LOCKIN_MODEL=claude-haiku-4-5,
LOCKIN_ACCESS_TOKEN, LOCKIN_DB_PATH=/var/lib/lockin/missions.db,
LOCKIN_INCIDENT_PATH=/var/log/lockin/storage.incidents.jsonl et
LOCKIN_ALLOWED_ORIGINS=https://lockin-demo.netlify.app.

Construire un nouveau dossier de publication :

```sh
python scripts/build_netlify.py --api-base https://adamzou.fr/lockin-api --output /tmp/lockin-netlify-real
```

Publier uniquement ce dossier sur le projet Netlify lockin-demo. `version.json`
identifie le commit et le mode réel ; `?demo` reste un choix explicite de simulation.
Les appels API, y compris le flux SSE, rejoignent directement le backend HTTPS
avec Bearer et une liste CORS limitée, sans proxy Netlify soumis à un délai court.

Avant bascule : sauvegarder la configuration Nginx existante et l'éventuelle base,
vérifier `nginx -t`, la sonde HTTPS, les 401 sans jeton, CORS, puis une mission
réelle bornée avec journal et streaming. Un dossier de release immuable et un
lien `/opt/lockin/current` permettent un retour à la release précédente.
Les missions de production sont conservées sur le VPS ; les veilles locales ne
sont pas transférées automatiquement.
