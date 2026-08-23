# GoPool Variable Speed Pump — custom_component

Intégration HACS dédiée pour la pompe GoPool AG1/IG1/IG2, en remplacement de
la configuration manuelle via localtuya + template YAML. Entités créées
automatiquement (dérivées de `const.py::DP_MAP`, seulement les DP confirmés
fonctionnels localement — voir le README principal du projet).

Testée avec succès en conditions réelles (pompe derrière un bridge wifi).

## Installation

1. Copie `custom_components/gopool_pump/` dans `<config>/custom_components/`.
2. Redémarre Home Assistant.
3. Réglages → Appareils et services → Ajouter une intégration →
   "GoPool Variable Speed Pump".
4. Entre le code utilisateur de ton app Smart Life / Tuya Smart, scanne le
   QR affiché avec l'app, puis choisis ta pompe dans la liste et confirme
   son adresse IP locale.

Une fois configurée, l'intégration est 100% locale — aucun appel cloud
supplémentaire après ce flux d'installation.

## Comment ça fonctionne

Réutilise le mécanisme officiel `tuya-device-sharing-sdk` (le même que
l'intégration Tuya native de Home Assistant pour son propre login QR),
avec l'identifiant client public `HA_3y9q4ak7g4ephrvke` / schema
`haauthorize` que Tuya a délivré à Home Assistant — pas un secret propre à
ce projet. Ça fonctionne aujourd'hui selon les retours de la communauté
(voir `vineetchoudhary/tuya-local-key`), mais rien ne garantit que Tuya ne
limitera pas cet usage tiers un jour.

Le protocole local est fixé à la version 3.5 (seule version confirmée sur
cette ligne de pompes) — pas un choix à faire à l'installation.
