# JOURNAL — travailler avec l'IA sur Lockin

Sept entrées tirées des 66 commits et de mesures réellement faites. Chaque essai
est marqué **simulé** (fournisseur factice, aucun coût) ou **réel** (appel Haiku
4.5 effectivement passé). Rien n'est raconté qui n'ait été observé.

---

**1. Lundi 07/09 — Deux IA qui se relisent trouvent ce qu'une seule ne voit pas.**
Claude et Codex ont travaillé en parallèle, chacun sur ses fichiers, avec relecture
croisée obligatoire. Codex a trouvé quatre erreurs chez Claude. La pire :
l'exclusion « aucun appel sortant vers un service tiers », qui contredisait
frontalement une mission de veille web. Une autre : affirmer que le balisage du
contenu non fiable protège de l'injection, alors qu'il réduit le risque sans
garantir l'obéissance du modèle. *Résultat* : la frontière est désormais entre lire
et écrire, et les contrôles serveur sont la protection décisive, le balisage
seulement en second. *Limite* : cette relecture coûte du temps, et n'a été possible
que parce que les périmètres étaient attribués nommément dès le départ.

**2. Lundi 07/09 — Une affirmation de sécurité non vérifiée est un mensonge.**
`compose.yaml` publiait `"8000:8000"` pendant que `MENACES.md` affirmait une écoute
locale seulement. Faux : Docker publie sur toutes les interfaces, donc sur le
réseau du hackathon. Sorti par `docker compose config`, pas par relecture — le
fichier se lisait très bien. *Résultat* : `127.0.0.1:8000:8000`, vérifié dans la
sortie. Ce qu'un document de menaces affirme doit être prouvé par une commande.

**3. Lundi 07/09 — Le placeholder qui passait la validation.** Le jeton d'exemple
faisait 47 caractères, le minimum exigé est 32 : `cp .env.example .env` puis
démarrage donnait une application **qui fonctionne**, avec un jeton lisible par
quiconque ouvre le dépôt. *Résultat* : valeur volontairement trop courte, refus au
démarrage avec message explicite. Échouer bruyamment plutôt qu'en silence.
*Vérifié* (simulé) sur clone neuf : 503 explicite sans secrets, démarrage complet
avec.

**4. Lundi 07/09 — Essai réel : onze sources lues, zéro constat.** **Essai réel
Haiku 4.5**, budget 18 actions. Observé : 11 sources lues, arrêt propre, **aucun
constat**. En démonstration, un écran vide. Le journal a donné la cause : le prompt
se contredisait — sauvegarder immédiatement, puis réserver les dernières actions à
la sauvegarde — et le modèle a suivi la seconde consigne ; sa tentative unique a
échoué parce que la citation devait être une sous-chaîne exacte de la page.
*Résultat* : contradiction supprimée, citations ancrées par identifiant fourni par
le serveur. Aucun test simulé n'aurait révélé ce biais : c'est la dépense la mieux
employée de la semaine.

**5. Mardi 08/09 — Diffuser la progression sans diffuser du provisoire.** Le flux
distingue le **journal** persisté, numéroté, qui fait foi et se rejoue après
coupure, et le **brouillon**, fragment du fournisseur, sans numéro, jamais rejoué,
jamais exécuté. Trois garde-fous vérifiés en **simulé** : arguments assemblés
seulement une fois le bloc clos, JSON tronqué neutralisé au lieu d'être exécuté,
raisonnement interne ignoré à la source. *Limite* : la recherche web n'est pas
diffusée au fil de l'eau, son résultat arrive d'un bloc.

**6. Mardi 08/09 — Ne pas confondre « l'agent est arrêté » et « je ne le vois
plus ».** Quatre situations distinctes : arrêt demandé, arrêt confirmé, échec —
tous trois venant du serveur — et connexion perdue, qui vient du navigateur et ne
dit rien de l'agent. Une connexion perdue **prime sur le dernier statut connu**, et
le message dit que l'agent n'est pas arrêté pour autant. Les incidents sont
horodatés à la **détection**, avec la mention que l'heure réelle d'une coupure
serveur est inconnue, et exportés à part du journal. *Vérifié* (simulé) : 16
contrôles, plus un rendu en navigateur réel sans erreur console.

**7. Mardi 08/09 — Cinquante-deux essais de robustesse, aucune correction
nécessaire.** **Simulé**, fournisseur comptant ses sollicitations : entrées vides,
blanches, trop longues, mal typées, hors bornes, domaines interdits, identifiants
inexistants, doubles soumissions, API coupée. Chaque refus produit un message
explicite et le compteur reste à **zéro**. `app/main.py` livré **inchangé** : c'est
un résultat, pas une omission. Il aurait été facile de fabriquer une correction
pour avoir quelque chose à montrer.

**Ce que les CTF ont confirmé.** Lundi : *un secret côté client n'est pas un
secret*. Mardi : le flag dormait dans un blob Git qu'un commit intitulé « security :
la clé ne doit jamais être en dur » prétendait avoir retiré — *rien ne s'efface*.
Les deux leçons étaient déjà écrites dans `MENACES.md` avant les épreuves.
*La chasse ouverte n'est pas traitée ici, par décision de l'équipe.*

---

## Dette technique assumée

Quatre dettes, vérifiées dans le code avant d'être décrites.

**1. Les citations ne couvrent qu'une partie de chaque page.** Le serveur découpe
une page en passages d'environ 450 caractères, **24 au maximum**, et n'en expose
que **six, de la dernière page lue**. *Raison* : borner le contexte, une seule
recherche web consommant déjà une part importante des 200 000 tokens de Haiku.
*Conséquence* : un fait au-delà du vingt-quatrième passage n'est pas citable par
identifiant ; le modèle doit retomber sur une citation brute validée par
correspondance exacte, le mécanisme même qui avait produit zéro constat lundi.
*Amélioration* : choisir les passages par pertinence au sujet plutôt que par ordre
d'apparition.

**2. Le seuil de tokens est un portail, pas un plafond.** 16 000, 24 000 ou 40 000
selon le budget d'actions, vérifié **avant de lancer** un appel, jamais pendant.
*Raison* : c'est le seul contrôle qui n'exige pas d'estimer à l'avance le coût d'un
appel dont la recherche web ramène un contenu de taille inconnue. *Conséquence* :
l'appel qui franchit le seuil est payé **en entier** ; le budget borne le nombre
d'appels lancés, pas la dépense. *Amélioration* : compter les tokens de l'appel à
venir et le refuser s'il ferait franchir le seuil.

**3. La consommation mesurée peut sous-estimer la réelle.** Un rapport d'usage
malformé est ignoré dans le total. *Raison* : ne jamais inventer un chiffre, un
rapport illisible ne vaut pas zéro token. *Conséquence* : le portail ci-dessus
laisse alors passer plus d'appels que prévu. Le code l'assume et expose un compteur
`unmeasured_calls` distinct. *Amélioration* : compter un appel non mesuré à la
moyenne observée plutôt qu'à zéro.

**4. Une mission interrompue est close, pas reprise.** Au redémarrage, une mission
non terminée est détectée puis **arrêtée** ; la reprise au point exact, annoncée
comme bonus du sujet, n'est pas implémentée. *Raison* : la reprise supposerait de
savoir quelle action était en vol, ce que le code ne sait pas — il l'écrit, le champ
`interrupted_at` reste nul. *Conséquence* : le travail validé est conservé, la
mission ne repart pas seule. *Amélioration* : rendre chaque action idempotente et
rejouable, pour qu'une reprise ne compte pas deux fois la même dépense.

---

**État de la répétition.** Elle **n'a pas encore eu lieu** au moment où ces lignes
sont écrites. Le parcours de quatre minutes existe dans `PALIER5_TESTS.md` mais n'a
pas été joué en conditions ; aucun chronométrage réel n'est revendiqué.

**À la livraison** : 66 commits, 342 tests automatisés qui passent, aucun appel
payant nécessaire pour les rejouer.
