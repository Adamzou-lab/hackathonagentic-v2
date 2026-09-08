# Palier 5 — Robustesse des entrées HTTP

Périmètre de ce document : validation des entrées de l'API et refus explicites.
Le moteur, les prompts, les preuves et les mesures de consommation relèvent de
Codex ; l'affichage du coût relève de Panaki. Ils ne sont pas couverts ici.

## Comment lire ce document

Deux natures d'essais, jamais mélangées.

| Marque | Signification |
| --- | --- |
| **Simulé** | Exécuté avec un fournisseur factice. Aucun appel réseau, aucun coût. Le résultat observé est reproductible par `pytest`. |
| **Réel (prévu)** | Scénario défini mais **non exécuté** à ce jour. Aucun résultat n'est revendiqué. |

Aucun essai avec Haiku réel n'a été mené pour cette partie : la robustesse des
entrées se démontre sans dépenser un centime, et une entrée refusée n'atteint
jamais le fournisseur par construction. Les lignes « Réel (prévu) » restent donc
sans résultat observé, et c'est volontaire.

## Preuve commune à tous les essais simulés

Le fournisseur factice compte chaque sollicitation. Chaque test de validation
vérifie que ce compteur reste à **zéro** : un refus d'entrée n'a donc jamais
déclenché d'appel facturable.

Commande : `pytest tests/test_api_robustesse.py -q` → **52 passés**.
Sortie brute des réponses : `python /tmp/probe.py` (script de relevé, joint plus bas).

---

## 1. Entrées vides, blanches et trop longues

| Entrée | Résultat attendu | Résultat observé | Preuve | Limite |
| --- | --- | --- | --- | --- |
| `subject: ""` | Refus explicite | **422** · « String should have at least 1 character » | `test_sujet_vide` | Message en anglais, produit par la bibliothèque de validation |
| `subject: "   \t "` | Refus : des espaces ne sont pas un sujet | **422** · « Value error, Sujet obligatoire. » | `test_sujet_uniquement_espaces` | — |
| `subject` de 501 caractères | Refus | **422** · « String should have at most 500 characters » | `test_sujet_trop_long` | — |
| `subject` de 500 caractères | **Accepté** : la borne est inclusive | **202** | `test_sujet_a_la_limite_accepte` | Vérifie qu'on n'a pas durci la borne par erreur |
| Corps `{}` | Refus | **422** · « Field required » | `test_corps_vide` | — |
| Corps non JSON | Refus, pas d'erreur 500 | **422** | `test_corps_non_json` | — |

## 2. Types incorrects

Le modèle est déclaré en mode strict : aucune conversion silencieuse.

| Entrée | Résultat attendu | Résultat observé | Preuve |
| --- | --- | --- | --- |
| `subject: 123` | Refus | **422** · « Input should be a valid string » | `test_types_incorrects` |
| `subject: null` / `["liste"]` | Refus | **422** | idem |
| `domains: "www.anthropic.com"` (chaîne au lieu de liste) | Refus | **422** · « Input should be a valid list » | idem |
| `domains: [42]` | Refus | **422** | idem |
| `action_budget: "3"` (chaîne numérique) | Refus, **sans conversion** | **422** · « Input should be a valid integer » | idem |
| `action_budget: 3.5` | Refus | **422** | idem |
| `duration_minutes: true` | Refus | **422** | idem |
| `auto_sources: "oui"` | Refus | **422** | idem |
| Champ `admin: true` non prévu | Refus, pas d'ignorance silencieuse | **422** · « Extra inputs are not permitted » | `test_champ_inconnu_refuse` |

Le refus d'un champ inconnu compte : un champ ignoré en silence laisserait croire
qu'un paramètre a été pris en compte alors qu'il n'a rien fait.

## 3. Paramètres hors bornes

| Entrée | Résultat attendu | Résultat observé | Preuve |
| --- | --- | --- | --- |
| `action_budget: 0` / `-1` | Refus | **422** · « greater than or equal to 1 » | `test_bornes_numeriques` |
| `action_budget: 101` | Refus | **422** · « less than or equal to 100 » | idem |
| `duration_minutes: 0` / `-5` / `31` | Refus | **422** · « less than or equal to 30 » | idem |
| 6 domaines | Refus | **422** · « List should have at most 5 items after validation, not 6 » | `test_trop_de_domaines` |
| `domains: ["https://www.anthropic.com"]` | Refus : URL, pas un hôte | **422** · « Indiquer un nom de domaine public, sans URL ni joker. » | `test_domaines_refuses` |
| `domains: ["www.anthropic.com/blog"]` | Refus : chemin | **422** | idem |
| `domains: ["*.anthropic.com"]` | Refus : joker | **422** | idem |
| `domains: ["127.0.0.1"]`, `["10.0.0.5"]` | Refus : adresse IP | **422** | idem |
| `domains: ["localhost"]`, `["x.internal"]`, `["x.local"]` | Refus : non public | **422** | idem |
| `auto_sources: true` **et** `domains` fournis | Refus : modes exclusifs | **422** · « En mode automatique, les domaines sont choisis par l'agent. » | `test_modes_de_sources_exclusifs` |
| Ni `auto_sources` ni `domains` | Refus | **422** · « Choisissez les sources automatiques ou au moins un domaine. » | idem |

Le refus des adresses IP, de `localhost` et des suffixes internes ferme la porte
aux requêtes vers le réseau interne de la machine hôte. C'est une protection, pas
une simple validation de forme.

## 4. Identifiants inexistants

| Requête | Résultat attendu | Résultat observé | Preuve |
| --- | --- | --- | --- |
| `GET /api/missions/inexistante` | 404 explicite | **404** · « Mission introuvable. » | `test_identifiants_inexistants` |
| `GET /api/missions/inexistante/events` | 404 | **404** · « Mission introuvable. » | idem |
| `GET /api/missions/inexistante/stream` | 404, pas un flux vide | **404** · « Mission introuvable. » | idem |
| `GET /api/watches/inexistante` | 404 | **404** · « Veille introuvable. » | idem |
| `POST /api/missions/inexistante/stop` | 404 | **404** · « Mission introuvable. » | `test_arret_mission_inexistante` |
| `watch_id: "jamais-vue"` au lancement | 404 avant tout appel payant | **404** · « Veille introuvable. » | `test_veille_inexistante_au_lancement` |
| Identifiants absurdes : `../../etc/passwd`, 300 caractères, `%00`, `null` | 404 ou 422, **jamais 500** | **404 / 422** | `test_identifiant_hors_format` |

## 5. Authentification

| Requête | Résultat attendu | Résultat observé | Preuve |
| --- | --- | --- | --- |
| Sans en-tête | 401 | **401** | `test_authentification_requise` |
| `Bearer mauvais` (trop court) | 401 | **401** | idem |
| `Bearer` + 40 caractères faux | 401 | **401** | idem |
| Jeton sans le préfixe `Bearer` | 401 | **401** | idem |
| `Basic` au lieu de `Bearer` | 401 | **401** | idem |

Un mauvais jeton de longueur valide est refusé : la contrainte de longueur ne
sert pas de laissez-passer, la comparaison porte bien sur la valeur.

## 6. Doubles soumissions

Essais menés avec un fournisseur qui ne rend jamais la main, afin que la première
mission soit réellement encore en cours au moment de la seconde.

| Séquence | Résultat attendu | Résultat observé | Preuve | Limite |
| --- | --- | --- | --- | --- |
| Deux fois la même demande, première en cours | Pas de seconde mission payante | **200** · `reuse: {reason: "already_running", window_hours: 24}`, **même identifiant** | `test_double_soumission_pendant_execution` | — |
| Sujet différent pendant qu'une mission tourne | Refus explicite | **409** · « Une mission est déjà en cours. » | `test_seconde_mission_differente_refusee` | — |
| Boucles d'agent démarrées sur ces trois requêtes | 1 | **1** | compteur `lancements` du fournisseur | — |

**Limite constatée, à signaler à Codex.** Lorsque la première mission est déjà
**terminée**, une soumission identique ne réutilise pas : elle crée une nouvelle
mission d'enrichissement rattachée à la même veille, avec `base_mission_id`
renseigné. C'est cohérent avec la fonction de veille, mais cela signifie qu'un
double clic après la fin d'une mission peut relancer un travail facturable. Le
comportement est peut-être voulu ; il n'est pas documenté aujourd'hui.

## 7. Recherche avec API désactivée

| Séquence | Résultat attendu | Résultat observé | Preuve |
| --- | --- | --- | --- |
| `POST /api/control {enabled:false}` puis lancement | Refus explicite, aucun appel payant | **409** · `{"code":"api_disabled","message":"API désactivée. Réactivez-la pour lancer une recherche. Aucun appel payant n'a été effectué."}` | `test_recherche_refusee_quand_api_desactivee` |
| Compteur du fournisseur après le refus | Inchangé | **inchangé** | même test |
| Réactivation puis lancement | Accepté | **202** | `test_reactivation_reautorise` |
| `POST /api/control` avec `{}`, `{"enabled":"oui"}`, `{"enabled":1}`, `{"active":true}` | Refus | **422** | `test_control_type_incorrect` |

Le message porte un code machine (`api_disabled`) et une phrase lisible qui dit
explicitement qu'aucun appel payant n'a eu lieu. C'est la réponse la plus
importante du palier : elle est la seule que l'utilisateur verra s'il coupe l'API.

## 8. Garantie transversale

`test_aucune_mission_creee_par_une_entree_invalide` enchaîne sept entrées
invalides de natures différentes, puis vérifie que le compteur du fournisseur est
resté à zéro et qu'aucun identifiant de mission n'a été distribué.

**Résultat observé : 0 appel, 0 mission.**

---

## Ce que ces essais ne couvrent pas

Dit franchement, pour ne pas laisser croire à une couverture plus large.

- **Aucun essai avec Haiku réel** dans cette partie. La robustesse des entrées se
  vérifie sans le fournisseur, et le vérifier avec lui n'apporterait rien qu'une
  facture.
- **Aucune vérification de la boucle de l'agent**, des prompts, de la qualité des
  preuves ni des mesures de consommation : périmètre de Codex.
- **Aucune vérification de l'affichage du coût** : périmètre de Panaki.
- **Les messages de validation restent en anglais** lorsqu'ils viennent de la
  bibliothèque (longueur, type). Seules les règles écrites par l'équipe parlent
  français. Corrigeable, non corrigé : cela toucherait `app/schemas.py`, hors de
  mon périmètre.
- **La charge simultanée n'est pas testée** : un seul client à la fois.

## Changements à signaler hors de mon périmètre

Aucune modification de `app/main.py` ne s'est révélée nécessaire : toutes les
entrées testées produisent déjà un refus explicite avant le moindre appel payant.
Le fichier est livré inchangé, et c'est un résultat en soi.

Deux points relèvent de fichiers que je ne dois pas modifier :

1. **`app/schemas.py`** — `localhost`, `x.internal` et `x.local` sont bien
   refusés, mais avec le message générique « Indiquer un nom de domaine public,
   sans URL ni joker. » plutôt qu'avec « Domaine non public. » qui existe pourtant
   juste en dessous. La règle de forme se déclenche avant. Le refus est correct,
   seule l'explication est imprécise.
2. **`app/schemas.py`** — les messages de longueur et de type restent en anglais.
   Un `json_schema_extra` ou des validateurs dédiés les mettraient en français.

---

## Parcours de démonstration, quatre minutes

À jouer devant l'examinateur, sans aucun appel payant. Chronométrage indicatif.

**0:00 — Le refus le plus parlant.** Couper l'API depuis l'interface, puis lancer
une recherche. Montrer la réponse : code `api_disabled` et la phrase « Aucun appel
payant n'a été effectué. » Dire pourquoi ce message existe : c'est le seul que
verra quelqu'un qui a coupé l'API sans s'en souvenir.

**0:45 — Les entrées qui ne passent pas.** Dans l'interface ou avec `curl`,
enchaîner : sujet vide, sujet composé d'espaces, budget à 0, six domaines, une URL
à la place d'un nom d'hôte. Cinq refus, cinq messages différents. Insister sur le
sujet composé d'espaces : il passe la contrainte de longueur et se fait rattraper
par une règle écrite exprès.

**1:45 — Ce qu'on refuse pour des raisons de sécurité.** Tenter `127.0.0.1`, puis
`localhost`, puis `service.internal`. Expliquer que ce n'est pas de la mise en
forme : sans ce filtre, un agent autonome pourrait être dirigé vers le réseau
interne de la machine qui l'héberge.

**2:30 — Le double clic.** Lancer une mission, puis relancer la même demande
pendant qu'elle tourne. Montrer que la réponse renvoie **le même identifiant**
avec `reuse: already_running`, et non une seconde mission. Puis tenter un sujet
différent : 409, refus explicite. Dire honnêtement la limite : après la fin d'une
mission, une demande identique crée une mission d'enrichissement.

**3:15 — La preuve chiffrée.** Lancer `pytest tests/test_api_robustesse.py -q`
devant eux : 52 tests, moins d'une seconde, zéro appel réseau. Montrer le
compteur du fournisseur factice dans le code et expliquer l'assertion qui compte
vraiment : `assert client.provider.appels == 0`. C'est elle qui prouve qu'une
entrée refusée ne coûte rien.

**3:50 — Conclure sur ce qui n'est pas couvert.** Annoncer soi-même les limites de
la section précédente plutôt que de les laisser trouver. Un périmètre annoncé se
défend mieux qu'un périmètre découvert.
