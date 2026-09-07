# PARCOURS.md — Le Métronome

Maquette du parcours utilisateur pour l'agent de veille web autonome. Une seule page, cinq zones, dans l'ordre où l'œil les rencontre.

## Maquette (texte)

```
┌─────────────────────────────────────────────────────────────────┐
│  LE MÉTRONOME — Veille web autonome                              │
├─────────────────────────────────────────────────────────────────┤
│  1. CONFIGURATION                                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Sujet de veille        [_________________________________] │  │
│  │ Domaines autorisés     [_________________________________] │  │
│  │                         (liste, un domaine par ligne ou     │  │
│  │                          séparés par virgule)                │  │
│  │ Budget d'actions       [ 20 ]  (nombre max de pages/requêtes)│  │
│  │                                                               │  │
│  │              [ ▶ Lancer la veille ]                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  2. ÉTAT EN COURS (visible seulement pendant l'exécution)        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Statut : ● En cours                                          │  │
│  │ Budget restant : 14 / 20 actions                             │  │
│  │ Sources consultées (5) :                                     │  │
│  │   ✓ https://exemple-source-1.org/article        [ok]        │  │
│  │   ✓ https://exemple-source-2.org/page           [ok]        │  │
│  │   ✗ https://exemple-source-3.org/inaccessible   [erreur]    │  │
│  │   ✓ https://exemple-source-4.org/rapport        [ok]        │  │
│  │   … en cours : https://exemple-source-5.org      [pending]  │  │
│  │                                                               │  │
│  │              [ ■ Arrêter l'agent ]                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  3. SYNTHÈSE                                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ (partielle si arrêt en cours de route, complète sinon)       │  │
│  │ Texte de synthèse …                                          │  │
│  │ Sources citées : [1] [2] [3] …                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  4. JOURNAL                                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 10:02:01  START   sujet="..." budget=20                      │  │
│  │ 10:02:03  FETCH    exemple-source-1.org → ok (200)           │  │
│  │ 10:02:05  FETCH    exemple-source-3.org → erreur (timeout)   │  │
│  │ 10:02:07  COMPARE  2 sources en accord                       │  │
│  │ 10:02:40  STOP     arrêt manuel, budget restant=14            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Détail des zones

### 1. Saisie et lancement
- **Sujet** : champ texte libre, obligatoire.
- **Domaines autorisés** : liste de domaines/URLs racines ; c'est la frontière de ce que l'agent a le droit de consulter.
- **Budget** : nombre entier d'actions (requêtes/pages), obligatoire, avec une valeur par défaut raisonnable.
- **Bouton de lancement** : désactivé tant que sujet + domaines + budget ne sont pas valides.

### 2. État en cours
- **Statut** : en cours / arrêté (budget épuisé) / arrêté (manuel) / terminé.
- **Budget restant** : compteur qui décroît en temps réel, visible sans rafraîchir la page.
- **Sources consultées** : liste chronologique, chaque entrée avec son statut (ok / erreur / en cours).
- **Bouton d'arrêt** : visible uniquement pendant l'exécution, déclenche l'arrêt immédiatement (pas de nouvelle action lancée après le clic).

### 3. Synthèse
- Affichée dès qu'il existe au moins un résultat exploitable, même si l'agent tourne encore ou a été arrêté (synthèse partielle).
- Chaque affirmation renvoie à une ou plusieurs sources consultées.

### 4. Journal
- Liste chronologique et horodatée des événements (démarrage, consultation de page, erreur, comparaison, arrêt).
- Doit permettre de reconstituer l'état exact de l'agent à n'importe quel instant, y compris après un arrêt.

## Hors scope de cette maquette
- Pas d'authentification / gestion multi-utilisateur.
- Pas d'historique de veilles passées (une session à la fois).
- Pas de configuration avancée du modèle (prompt, température, etc.) exposée à l'utilisateur.
