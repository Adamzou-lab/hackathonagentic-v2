"""Diffusion progressive des évènements de mission.

Deux natures d'évènements circulent, et le client ne doit jamais les confondre.

- `journal` : évènement déjà persisté par le moteur, porteur d'un `seq` monotone.
  Il fait foi, il est rejouable après reconnexion et se déduplique par `seq`.
- `draft`   : fragment provisoire reçu du fournisseur pendant qu'il rédige.
  Il n'a pas de `seq`, il n'est jamais rejoué, il n'est jamais exécuté. Il sert
  uniquement à montrer que le travail avance.

Le flux lit les évènements persistés depuis la base, jamais depuis la mémoire du
moteur : ce qui est diffusé a donc déjà survécu à un redémarrage.
"""
import asyncio
import json

HEARTBEAT_SECONDS = 15
DRAFT_QUEUE_MAX = 256


class Broker:
    """Bus mémoire des fragments provisoires du fournisseur.

    Volontairement non persistant : un fragment provisoire n'est pas une preuve.
    Les files sont bornées ; un client lent perd des fragments plutôt que de
    faire grossir la mémoire du serveur. Aucune perte de journal n'en découle,
    puisque le journal transite par la base et non par ce bus.
    """

    def __init__(self):
        self.subscribers = {}

    def subscribe(self, mid):
        queue = asyncio.Queue(maxsize=DRAFT_QUEUE_MAX)
        self.subscribers.setdefault(mid, set()).add(queue)
        return queue

    def unsubscribe(self, mid, queue):
        listeners = self.subscribers.get(mid)
        if not listeners:
            return
        listeners.discard(queue)
        if not listeners:
            self.subscribers.pop(mid, None)

    def publish(self, mid, payload):
        for queue in list(self.subscribers.get(mid, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # On sacrifie le fragment le plus ancien : l'affichage saute,
                # le journal reste complet.
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


def frame(event, data, seq=None):
    """Une trame SSE. `id` n'est posé que sur les évènements qui font foi."""
    head = f'id: {seq}\n' if seq is not None else ''
    body = json.dumps(data, ensure_ascii=False)
    return f'{head}event: {event}\ndata: {body}\n\n'


async def mission_stream(store, broker, mid, last_seq=0, poll=0.2, terminal=frozenset()):
    """Fusionne le journal persisté et les fragments provisoires, dans cet ordre.

    `last_seq` vient de l'en-tête `Last-Event-ID` : après une coupure, le client
    reprend exactement où il s'était arrêté, sans recevoir deux fois le même
    évènement. Les fragments provisoires, eux, ne sont jamais rejoués : ils
    décrivent un instant passé qui n'a plus de valeur.
    """
    queue = broker.subscribe(mid)
    idle = 0.0
    try:
        while True:
            sent = False

            # Le journal d'abord : il fait foi et il est ordonné par seq.
            for event in store.events(mid):
                if event['seq'] <= last_seq:
                    continue
                last_seq = event['seq']
                sent = True
                yield frame('journal', {
                    'mission_id': mid, 'seq': event['seq'], 'at': event['at'],
                    'kind': event['kind'], 'data': event['data'],
                }, seq=event['seq'])

            # Puis les fragments provisoires accumulés depuis le tour précédent.
            while True:
                try:
                    draft = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                sent = True
                yield frame('draft', draft)

            status = store.get(mid)['status']
            if status in terminal:
                # Un dernier tour a déjà été fait ci-dessus : le journal est vidé.
                yield frame('end', {'mission_id': mid, 'status': status, 'last_seq': last_seq})
                return

            idle = 0.0 if sent else idle + poll
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                # Garde la connexion ouverte à travers les proxys sans polluer
                # le flux d'évènements applicatifs.
                yield ': keepalive\n\n'
            await asyncio.sleep(poll)
    finally:
        broker.unsubscribe(mid, queue)
