# Synthèses Lockin

Le format suit une note de veille orientée décision :

1. **À retenir** : jusqu’à trois titres de constats réellement sauvegardés.
2. **Les faits et leur portée** : pour chaque constat, fait sourcé, implication distincte, date, niveau de corroboration et extraits exacts accessibles.
3. **Limites et points à vérifier** : mission partielle, dates inconnues, contexte ancien et sources uniques explicitement signalés.

Cette structure s’inspire des principes d’analyse ICD 203 de l’ODNI : distinguer les informations des interprétations, documenter les sources et expliquer les incertitudes. Ce n’est ni une certification ni une promesse de format universellement supérieur.
Source : https://www.dni.gov/files/documents/ICD/ICD-203.pdf

La mise en forme est déterministe, commune à la mission et à Mes veilles. Elle ne nécessite aucun appel IA supplémentaire. Le modèle produit des constats courts dans un schéma fixe. Les passages numérotés sont générés depuis le texte réellement lu ; le serveur résout leurs identifiants en citations exactes. Un identifiant inconnu, une page non lue ou une citation fabriquée restent refusés.

Optimisation : pack Rapide par défaut (10 actions, 5 minutes), cache de veille récente conservé, réutilisation des pages déjà lues dans une mission, contexte de preuves limité aux deux dernières pages (12 passages chacune), et deux dernières actions réservées aux sauvegardes ou à la clôture lorsqu’une page est disponible. Le modèle conserve le choix du constat ou de terminer sans résultat. Les anciennes missions vides ne sont pas réécrites artificiellement.

Une limite de budget n’assure pas un coût financier fixe : les appels modèle, leurs tokens et les recherches web sont journalisés séparément. Une source bloquée reste bloquée. Une synthèse sans nouveauté est possible et ne doit jamais être remplacée par des faits inventés.
