# Consommation et progression

Les nouvelles missions ont un seuil de tokens : 16 000 jusqu'à 10 actions,
24 000 jusqu'à 20 actions, 40 000 au-delà. Le moteur vérifie les consommations
reçues avant chaque nouvel appel au modèle (décision, découverte et recherche).
Au seuil atteint, il journalise `token_budget_exhausted` et conserve les constats
existants avec le statut `budget_exhausted`.

Ce seuil n'est pas un plafond de facturation strict : la consommation du dernier
appel est connue après son retour, et les appels interrompus peuvent être facturés
sans bilan disponible. L'interface le précise. Les anciens résultats réutilisés
gardent leur consommation historique ; cette modification ne réécrit pas les logs.

Réductions appliquées : consignes principales de 4 437 à 1 875 caractères ; une
page et six passages dans le contexte au lieu de deux pages et douze passages
chacune ; deux résultats récents au lieu de quatre ; suppression des candidats
après sélection des domaines ; contrôle de périmètre limité au sujet et ses
paramètres ; réponses de décision limitées à 1 024 tokens. La recherche web native
garde sa limite de 2 048 tokens pour éviter une troncature de ses résultats.
Les sources complètes restent conservées côté serveur, avec les citations vérifiées.
La réduction réelle des tokens et la qualité sont à comparer sur les prochaines
missions : aucun pourcentage d'économie global n'est garanti par ces tests.

Streaming : fragments reçus regroupés toutes les 80 ms, bloc stable pendant les
appels, arguments techniques repliables, pas de reconstruction des constats
inchangés. Aucun texte n'est inventé pour simuler une progression. Les jauges
respectent la préférence de réduction des animations.

Validation : 342 tests Python, 12 tests frontend, 7 contrôles consommation et
évaluation autonome 10/10. Aucun appel payant nécessaire à ces vérifications.
