# GoPool Variable Speed Pump — custom_component

Intégration HACS dédiée pour la pompe GoPool AG1/IG1/IG2, en remplacement de
la configuration manuelle via localtuya + template YAML. Entités créées
automatiquement (dérivées de `const.py::DP_MAP`, seulement les DP confirmés
fonctionnels localement — le DP "Schedule" a été retiré après confirmation
qu'il n'a aucun effet).

Testée avec succès en conditions réelles (pompe derrière un bridge wifi).

## Installation

1. Copiez `custom_components/gopool_pump/` dans `<config>/custom_components/`.
2. Redémarrez Home Assistant.
3. Réglages → Appareils et services → Ajouter une intégration →
   "GoPool Variable Speed Pump".
4. Entrez le code utilisateur de votre app Smart Life / Tuya Smart, scannez
   le QR affiché avec l'app, puis choisissez votre pompe dans la liste et
   confirmez son adresse IP locale. Le config flow détaille chaque étape.

Une fois configurée, l'intégration est 100% locale — aucun appel cloud
supplémentaire après ce flux d'installation (voir l'avertissement sur la
local key dans le config flow si vous retirez la pompe de Smart Life).

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

## Entités

- `switch` : Power, Quick Clean, No Load Protection.
- `number` : Current Speed, Quick Clean Speed/Duration, Timeout Duration,
  Stage 1-4 Speed/Duration.
- `time` : Stage 1-4 Start Time — un seul sélecteur HH:MM par stage
  (combine les DPs heure et minute de la pompe). La pompe n'accepte les
  minutes que par pas de 10 ; toute valeur choisie est arrondie vers le bas
  au pas de 10 minutes le plus proche avant d'être envoyée.

## Images du config flow (`docs/images/`)

Deux GIFs sont référencés dans le texte du config flow via des liens
`raw.githubusercontent.com` pointant sur `main` — ils doivent donc être
présents à ces chemins exacts dans le repo (pas dans
`custom_components/gopool_pump/`, puisque ce dossier est ce que HACS
installe chez l'utilisateur — les images, elles, sont seulement chargées
depuis GitHub par le navigateur, pas depuis le disque local) :

- `docs/images/user_code.gif` — comment trouver le code utilisateur dans
  Smart Life (étape "Lier votre compte").
- `docs/images/qr_scan.gif` — comment scanner le code QR dans Smart Life
  (étape "Scannez ce code QR").
