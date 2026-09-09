# Outils de l'agent — palier 1

Contrat de conception, sans implémentation. Mission de démo : nouveautés des sept derniers jours sur les frameworks et outils d'IA agentique, avec synthèse dédupliquée, datée et sourcée. Le sujet et les sources restent configurables pour une évaluation sur des données nouvelles.

## Ce que le modèle peut demander

Le modèle choisit ses recherches, les pages à lire et les constats à conserver. Le programme valide chaque demande et impose les limites ; le modèle ne peut ni augmenter son budget ni désactiver l'arrêt.

Les signatures ci-dessous utilisent une notation de types descriptive, pas du code à exécuter. `Result[T]` signifie soit `Success(value: T)`, soit `Failure(error: ToolError)` ; `list[T]` est une liste, `T | null` une valeur facultative.

| Nom | Signature typée | Effet de bord ? |
| --- | --- | --- |
| `search_web` | `search_web(query: str, k: int) -> Result[list[SearchHit]]` | **Oui** : requête à un prestataire externe, consommation de quota et divulgation de la requête. Aucune modification des sites. |
| `read_page` | `read_page(url: HttpUrl) -> Result[Page]` | **Oui** : requête HTTP observable par le site, consommation réseau et stockage local d'une preuve bornée. Aucune modification volontaire du site. |
| `save_finding` | `save_finding(finding: FindingDraft, idempotency_key: str) -> Result[SavedFinding]` | **Oui** : écriture locale persistante d'un constat sourcé. |

Chaque tentative produit aussi des événements de journal et consomme le budget selon les règles ci-dessous. « Lecture seule sur le Web » ne signifie donc pas « aucun effet de bord ».

## Types échangés

| Type | Champs et sens |
| --- | --- |
| `HttpUrl` | Chaîne HTTPS soumise à validation côté serveur ; ce nom de type ne suffit pas à rendre une URL sûre. |
| `SearchHit` | `url: HttpUrl`, `title: str`, `snippet: str`, `published_at: str | null`. La date annoncée par la recherche reste non vérifiée ; un extrait de recherche n'est pas une preuve suffisante pour le rapport. |
| `Page` | `source_id: str`, `requested_url: HttpUrl`, `final_url: HttpUrl`, `title: str`, `text: str`, `published_at: str | null`, `retrieved_at: str`, `content_hash: str`, `truncated: bool`. Identifiant, horodatage UTC et empreinte produits par le programme ; date de publication extraite, sans garantie de vérité. |
| `Evidence` | `source_id: str`, `passage_id: str`. Référence à un extrait exact d'une page réellement lue ; le serveur résout le texte depuis la copie conservée. |
| `FindingDraft` | `title: str`, `summary: str`, `developer_impact: str`, `evidence: list[Evidence]`, `event_date: str | null`, `date_status: DateStatus`, `confidence: Confidence`, `caveats: list[str]`. Au moins une preuve ; une date inconnue n'est pas remplacée par la date de consultation. |
| `DateStatus` | Une valeur parmi `in_window`, `outside_window`, `unknown`. Fenêtre de sept jours calculée à partir du démarrage de la mission ; la classification reste à recouper avec les preuves. |
| `Confidence` | Une valeur parmi `single_source`, `corroborated`, `conflicting`. Deux pages recopiant la même annonce ne constituent pas deux confirmations indépendantes. |
| `SavedFinding` | `finding_id: str`, `disposition: SaveDisposition`. Identifiant stable et résultat de la déduplication. |
| `SaveDisposition` | Une valeur parmi `created`, `already_saved`. |
| `ToolError` | `code: ErrorCode`, `message: str`, `retryable: bool`. Message nettoyé, sans secret ni contenu HTML exécutable. |
| `ErrorCode` | Une valeur parmi `invalid_input`, `blocked_url`, `timeout`, `unavailable`, `rate_limited`, `too_large`, `unsupported_content`, `invalid_evidence`, `unsupported_claim`, `idempotency_conflict`, `storage_failure`, `cancelled`, `budget_exhausted`. |

## Contrats et limites proposés pour le MVP

Ces valeurs forment une base de conception à harmoniser avec `SPEC.md` et `MENACES.md`, puis à ajuster sur mesures. Elles ne prétendent pas démontrer à elles seules les 30 minutes d'autonomie.

- **Contexte imposé par le serveur** : mission courante, domaines autorisés, fenêtre temporelle, budgets et identité de l'opérateur. Aucun outil n'accepte un chemin de fichier, des identifiants ou un changement de permissions choisis par le modèle.
- **Recherche** : requête de 1 à 500 caractères, `k` entre 1 et 5. Le serveur restreint la recherche aux domaines autorisés et filtre aussi les résultats ; le filtre du prestataire n'est pas une garantie. Fournisseur de recherche : Anthropic web_search.
- **Lecture** : HTTPS public, sans compte ni cookie de session utilisateur ; refus des adresses locales, privées, réservées et des URL contenant des identifiants. Contrôler le domaine, la résolution réseau et la destination réellement jointe, à chaque redirection (3 maximum), pour éviter les accès au réseau interne. Limites proposées : 15 secondes par appel, 1 Mio reçu et 30 000 caractères de texte conservé par page. Pas d'exécution de JavaScript, de téléchargement arbitraire ou de navigation authentifiée ; page non exploitable = erreur explicite.
- **Contenus externes** : texte traité comme donnée non fiable. Les consignes trouvées dans une page ne changent ni la mission ni les permissions. Le rapport est rendu comme texte échappé, pas comme HTML fourni par un site.
- **Constats** : valider les types, les tailles et la présence effective des extraits dans les pages enregistrées. Un second appel modèle borné vérifie ensuite que ces extraits soutiennent réellement les affirmations. Il rejette en cas de contradiction, d'ambiguïté ou de soutien insuffisant ; cette étape réduit les inventions sans certifier la vérité de la source. Les incertitudes et contradictions restent visibles ; les dates inconnues ne sont pas présentées comme des nouveautés confirmées de la semaine.
- **Idempotence** : portée de la clé = exécution courante. Une même clé avec le même contenu rend le résultat existant ; un contenu différent rend `idempotency_conflict`. Une contrainte persistante empêche les doubles écritures. La déduplication sémantique des annonces reste une tâche distincte de comparaison des preuves.

## Contrôles du programme — pas des outils du modèle

**Budget et durée.** Proposition initiale : 100 tentatives d'outils, 60 appels au modèle, échéance de 30 minutes. Réserver un jeton de budget avant chaque tentative, y compris un échec ; aucun compteur négatif. Borner aussi les jetons par réponse du modèle. Au plus une nouvelle tentative sur erreur transitoire, comptabilisée et autorisée seulement si le budget, l'échéance et l'état d'arrêt le permettent. Un refus de permission n'est pas retenté. Le coût monétaire dépendra du fournisseur retenu ; aucun plafond en euros n'est promis à ce stade.

**Arrêt.** Le bouton d'arrêt appartient à l'opérateur, pas au modèle. Dès réception, le serveur enregistre la demande et interdit toute nouvelle action. Il annule l'appel en cours si possible ; sinon l'appel reste borné par son délai d'expiration (cible : 15 secondes, également pour les appels au modèle). L'interface distingue `stopping` de `stopped`. Ne pas prétendre annuler une requête déjà reçue par un service externe. Tout résultat arrivé pendant l'arrêt est tracé mais ne déclenche aucune action suivante.

**Journal et reconstruction.** Avant tout appel : écrire durablement l'identifiant d'exécution, le numéro d'événement, l'identifiant d'action, l'heure UTC, le nom de l'outil et ses paramètres nettoyés, les budgets restants et la décision structurée attendue. Après l'appel : enregistrer réussite, erreur ou annulation, durée et références des résultats. Conserver également les changements d'état et les demandes d'arrêt. Journal en ajout seulement, sans clés API ni raisonnement interne du modèle ; une brève justification de l'action suffit. Une action commencée sans résultat enregistré après une panne est marquée interrompue, résultat inconnu, jamais inventée comme réussie.

**Persistance.** Si le journal ne peut plus être écrit, arrêter le lancement d'actions et afficher une erreur ; ne pas continuer sans traces. Les écritures de constat et leur événement sont atomiques. L'utilisateur peut retrouver les sources, résultats, erreurs, compteurs et action en cours depuis les événements persistés.

**Synthèse et fin.** Les constats sourcés sont enregistrés au fil de l'eau. À l'arrêt, à l'échéance ou à l'épuisement du budget, rendre ces résultats par un assemblage déterministe, sans nouvel appel au modèle ; une synthèse partielle reste donc disponible. Une mission terminée normalement peut finir plus tôt sans attente artificielle. Un résultat vide est explicitement indiqué. États prévus : `pending`, `running`, `stopping`, `stopped`, `completed`, `budget_exhausted`, `deadline_reached`, `failed` ; état terminal et motif sont journalisés.

La reprise après panne au point exact est un bonus, pas une promesse du MVP. Reconstruire l'état depuis les traces fait en revanche partie du MVP.

## Alignement avec le cadrage de Claude

- L'ordre d'arrêt est un état **persisté en base**, relu avant chaque appel et chaque tour de boucle, y compris après redémarrage ; il ne repose pas uniquement sur un signal en mémoire.
- Deux tentatives maximum par URL source en échec pour toute l'exécution : rappeler le même outil plus tard ne remet pas le compteur à zéro. Les reprises restent réservées aux erreurs transitoires et consomment le budget.
- La lecture porte sur du HTML textuel, RSS ou Atom, sans PDF ni images. Le programme vérifie les règles d'accès de `robots.txt` et borne le débit par domaine ; une indisponibilité de ces règles suspend la source, sans contournement. Chaque redirection est revérifiée avant d'être suivie. Les requêtes de contrôle sont elles-mêmes tracées, bornées et comptées dans un plafond réseau distinct proposé à 200 requêtes, redirections comprises.
- Une actualisation peut recevoir un contexte factuel borné (20 constats, 12 000 caractères), versionné avec les identifiants des preuves et de la mission précédente. Les anciens journaux et les pages complètes ne sont pas réinjectés. Les constats antérieurs restent des données non fiables.

## À savoir expliquer au checkpoint

Le modèle propose les actions ; le serveur décide si elles sont autorisées. Les pages et le prestataire de recherche peuvent mentir. Les citations permettent de contrôler l'origine d'une information, pas de garantir sa vérité. Même si le modèle ignore une consigne d'arrêt, il ne peut plus lancer d'outil : c'est le programme qui coupe l'exécution.


## Découverte de sources et enrichissement

- `discover_sources(query)` : une recherche publique réelle retourne jusqu'à 10 candidats ; une seule tentative par exécution, erreur visible en cas d'échec.
- `select_sources(sources)` : le modèle propose 1 à 5 domaines présents dans ces candidats, avec un motif. Le serveur vérifie la liste et le DNS public avant de permettre les lectures. Impossible en mode manuel.
- `save_finding` : `change` vaut new, update ou duplicate ; les deux derniers référencent un `related_finding_id` connu. Toute preuve doit avoir été relue dans l'exécution actuelle.
- Chaque découverte et sélection compte dans le budget d'actions ; tous les appels modèle sont comptés.
- « Mes veilles » regroupe les exécutions dans une fiche durable. Une actualisation ne réécrit jamais les journaux ou les preuves des exécutions antérieures.
