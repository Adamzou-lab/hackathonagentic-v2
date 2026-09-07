# Lockin : une seule image. Le backend FastAPI sert aussi l'interface statique,
# donc un seul conteneur suffit et il n'y a pas de CORS a gerer.
FROM python:3.12-slim

# Pas de fichiers .pyc, et sortie non bufferisee pour voir les logs en direct
# pendant qu'une mission tourne.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Les dependances avant le code : tant que requirements.txt ne change pas,
# Docker reutilise cette couche et le rebuild reste rapide.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# L'agent tourne sans privileges. C'est une precaution volontaire : si une page
# consultee parvenait a influencer l'execution, elle le ferait avec les droits
# d'un utilisateur sans pouvoir, pas avec ceux de root.
RUN useradd --create-home --shell /usr/sbin/nologin lockin \
 && mkdir -p /app/data \
 && chown -R lockin:lockin /app
USER lockin

EXPOSE 8000

# Un seul worker : une seule mission active par serveur.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
