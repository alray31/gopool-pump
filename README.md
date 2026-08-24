[English version](README.en.md)

<img width="1398" height="678" alt="banner" src="https://github.com/user-attachments/assets/8ffd675d-dcd9-47bd-bc88-2c683837a494" />

# GoPool Variable Speed Pump

Intégration [HACS](https://hacs.xyz/) pour contrôler une pompe à vitesse
variable **GoPool / GoPiscine AG1, IG1 ou IG2** dans Home Assistant —
100 % locale une fois configurée.

## Pourquoi cette intégration

Ces pompes utilisent la puce Wi-Fi Tuya. Jusqu'ici, les contrôler dans Home
Assistant demandait de passer par localTuya et de récupérer soi-même le
`device_id` et la `local_key` via un compte développeur Tuya IoT — une étape
technique et fastidieuse pour un nouvel utilisateur. Cette intégration
automatise cette récupération grâce à une simple connexion (par QR code)
à votre compte Smart Life / Tuya Smart, puis fonctionne ensuite
entièrement en local, comme localTuya.

## Prérequis

- Votre pompe doit déjà être ajoutée dans l'application **Smart Life** (ou
  Tuya Smart), tel que décrit dans le manuel d'instructions fourni avec la
  pompe.
- Votre pompe doit être connectée à votre réseau local en Wi-Fi et se
  trouver sur le même sous-réseau que Home Assistant. Par exemple, si
  votre Home Assistant est sur `192.168.1.2`, l'adresse IP de votre pompe
  doit commencer par `192.168.1.x`.
- Connaître l'adresse IP de votre pompe (par exemple via le menu
  administrateur de votre routeur Wi-Fi). Il est fortement recommandé de
  lui assigner une adresse IP statique — si la pompe change d'adresse IP
  par la suite, il faudra reconfigurer cette intégration.
- Avoir votre téléphone ou votre tablette avec l'application **Smart
  Life** (ou Tuya Smart) à portée de main pendant la configuration de
  cette intégration.
- Home Assistant 2024.8.0 ou plus récent.
- [HACS](https://hacs.xyz/) installé.

## Installation

Cette intégration n'est pas (encore) dans le dépôt par défaut de HACS —
ajoutez-la comme dépôt personnalisé :

1. HACS → menu (⋮) en haut à droite → **Dépôts personnalisés**.
2. URL : `https://github.com/alray31/gopool-pump`, catégorie **Intégration**.
3. Recherchez "GoPool Variable Speed Pump" dans HACS et installez-la.
4. Redémarrez Home Assistant.

## Configuration

Réglages → Appareils et services → Ajouter une intégration → **GoPool
Variable Speed Pump**. Le config flow vous guide à travers 3 étapes :

1. **Lier votre compte** — entrez le code utilisateur de votre app Smart
   Life (Profil → Réglages → Compte et sécurité → Code utilisateur).
2. **Scanner le QR code** affiché, avec l'app Smart Life.
3. **Choisir votre pompe** dans la liste des appareils liés, et confirmer
   son adresse IP locale.

Chaque étape contient ses propres explications détaillées (avec captures
animées) directement dans l'interface — inutile de les répéter ici.

> **⚠️ Important :** cette étape de connexion au cloud Smart Life n'est
> nécessaire qu'une seule fois, pour récupérer automatiquement les
> identifiants locaux de la pompe. Ensuite, l'intégration ne communique
> plus jamais avec le cloud. Vous pouvez supprimer l'application Smart
> Life de votre téléphone si vous le souhaitez — mais **ne supprimez
> jamais la pompe de votre compte Smart Life** : cela changerait sa
> `local_key` et vous obligerait à reconfigurer l'intégration.

## Entités créées

| Type | Entité |
|---|---|
| `switch` | Power, Quick Clean, No Load Protection |
| `number` | Current Speed, Quick Clean Speed, Quick Clean Duration, Timeout Duration, Stage 1-4 Speed, Stage 1-4 Duration |
| `time` | Stage 1-4 Start Time (heure + minute combinées en un seul sélecteur) |

Seuls les DP (data points) confirmés fonctionnels localement sur ces
pompes sont exposés — les DP inertes (fault, schedule, motor_operation_state,
etc.) sont volontairement exclus.

## Comment ça fonctionne techniquement

- **Communication locale** via [tinytuya](https://github.com/jasonacox/tinytuya),
  protocole Tuya version 3.5 (seule version confirmée sur cette ligne de
  pompes — fixe, pas un choix à faire à l'installation).
- **Récupération des identifiants** via [tuya-device-sharing-sdk](https://pypi.org/project/tuya-device-sharing-sdk/),
  le même mécanisme que l'intégration Tuya officielle de Home Assistant
  pour son propre login QR, en réutilisant l'identifiant client public de
  Home Assistant (`HA_3y9q4ak7g4ephrvke`) — pas un secret propre à ce
  projet, ni besoin de créer un compte développeur Tuya IoT.
- Un polling local toutes les 30 secondes maintient l'état à jour.

## Limitations connues

- Le mécanisme de QR login réutilise un identifiant client appartenant à
  Home Assistant. Cela fonctionne aujourd'hui (confirmé par la communauté),
  mais Tuya pourrait un jour limiter cet usage tiers sans préavis.
- Testé sur GoPool AG1 ; les DP des IG1/IG2 sont supposément identiques
  mais pas encore confirmés sur le terrain.

## Problèmes de connexion locale

Si la pompe est injoignable après configuration :

- Vérifiez que la pompe et Home Assistant sont sur le même sous-réseau
  (particulièrement si la pompe est derrière un pont/bridge Wi-Fi).
- Confirmez que le port 6668 n'est pas bloqué par un pare-feu ou une
  isolation VLAN entre les deux appareils.
- Retirez, puis rajoutez l'intégration en repassant par le config flow —
  si la pompe a été retirée/rajoutée dans Smart Life entretemps, sa
  `local_key` a changé.

## Contribuer

Les retours, rapports de bogue et suggestions sont les bienvenus via les
[issues GitHub](https://github.com/alray31/gopool-pump/issues) de ce
dépôt.

## Licence

Voir [LICENSE](LICENSE).
