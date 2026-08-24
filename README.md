# GoPool Variable Speed Pump

<img width="1398" height="678" alt="banner" src="https://github.com/user-attachments/assets/8ffd675d-dcd9-47bd-bc88-2c683837a494" />

🇫🇷 [Français](#français) · 🇬🇧 [English](#english)

---

## Français

Intégration [HACS](https://hacs.xyz/) pour contrôler une pompe à vitesse
variable **GoPool / GoPiscine AG1, IG1 ou IG2** dans Home Assistant —
100 % locale une fois configurée.

### Pourquoi cette intégration

Ces pompes utilisent la puce Wi-Fi Tuya. Jusqu'ici, les contrôler dans Home
Assistant demandait de passer par localTuya et de récupérer soi-même le
`device_id` et la `local_key` via un compte développeur Tuya IoT — une étape
technique et fastidieuse pour un nouvel utilisateur. Cette intégration
automatise cette récupération grâce à une simple connexion (par QR code)
à votre compte Smart Life / Tuya Smart, puis fonctionne ensuite
entièrement en local, comme localTuya.

### Prérequis

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

### Installation

Cette intégration n'est pas (encore) dans le dépôt par défaut de HACS —
ajoutez-la comme dépôt personnalisé :

1. HACS → menu (⋮) en haut à droite → **Dépôts personnalisés**.
2. URL : `https://github.com/alray31/gopool-pump`, catégorie **Intégration**.
3. Recherchez "GoPool Variable Speed Pump" dans HACS et installez-la.
4. Redémarrez Home Assistant.

### Configuration

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

### Entités créées

| Type | Entité |
|---|---|
| `switch` (contrôle) | Power, Quick Clean |
| `switch` (configuration) | No Load Protection |
| `number` (contrôle) | Pump Speed |
| `number` (configuration) | Quick Clean Speed, Quick Clean Duration, Timeout Duration, Stage 1-4 Speed, Stage 1-4 Duration |
| `select` (configuration) | Stage 1-4 Start Time (heure + minute combinées en un seul sélecteur, valeurs limitées aux paliers de 10 minutes acceptés par la pompe) |
| `sensor` | Power Draw (W), Energy (kWh) — calculés à partir du RPM commandé et du modèle de pompe choisi à la configuration (voir [Contribuer](#contribuer) pour IG1/IG2) |

Seuls les DP (data points) confirmés fonctionnels localement sur ces
pompes sont exposés — les DP inertes (fault, schedule, motor_operation_state,
etc.) sont volontairement exclus.

### Comment ça fonctionne techniquement

- **Communication locale** via [tinytuya](https://github.com/jasonacox/tinytuya),
  protocole Tuya version 3.5 (seule version confirmée sur cette ligne de
  pompes — fixe, pas un choix à faire à l'installation).
- **Récupération des identifiants** via [tuya-device-sharing-sdk](https://pypi.org/project/tuya-device-sharing-sdk/),
  le même mécanisme que l'intégration Tuya officielle de Home Assistant
  pour son propre login QR, en réutilisant l'identifiant client public de
  Home Assistant (`HA_3y9q4ak7g4ephrvke`) — pas un secret propre à ce
  projet, ni besoin de créer un compte développeur Tuya IoT.
- Un polling local toutes les 3 secondes maintient l'état à jour, avec
  reconnexion automatique en cas d'échec ponctuel — même en cas d'échec
  ponctuel, les entités gardent leur dernière valeur connue au lieu de
  devenir indisponibles.
- Les capteurs **Power Draw** (W) et **Energy** (kWh) sont calculés
  directement par l'intégration (interpolation d'une courbe RPM→W, puis
  intégration trapézoïdale dans le temps) — aucun template ou aide HA
  n'est nécessaire.

### Limitations connues

- Le mécanisme de QR login réutilise un identifiant client appartenant à
  Home Assistant. Cela fonctionne aujourd'hui (confirmé par la communauté),
  mais Tuya pourrait un jour limiter cet usage tiers sans préavis.
- Testé sur GoPool AG1 ; les DP des IG1/IG2 sont supposément identiques
  mais pas encore confirmés sur le terrain.
- Les capteurs Power Draw / Energy affichent **indisponible** pour IG1 et
  IG2 : la courbe de calibration RPM→W n'existe pour l'instant que pour la
  AG1 (voir [Contribuer](#contribuer) ci-dessous).

### Problèmes de connexion locale

Si la pompe est injoignable après configuration :

- Vérifiez que la pompe et Home Assistant sont sur le même sous-réseau
  (particulièrement si la pompe est derrière un pont/bridge Wi-Fi).
- Confirmez que le port 6668 n'est pas bloqué par un pare-feu ou une
  isolation VLAN entre les deux appareils.
- Retirez, puis rajoutez l'intégration en repassant par le config flow —
  si la pompe a été retirée/rajoutée dans Smart Life entretemps, sa
  `local_key` a changé.

### Contribuer

**Vous possédez une pompe IG1 ou IG2 ?** Les capteurs **Power Draw** (W)
et **Energy** (kWh) reposent sur une courbe de calibration RPM → Watts
mesurée directement sur une pompe réelle. Pour l'instant, seule la courbe
de la **AG1** est disponible ; ces deux capteurs affichent donc
« indisponible » sur IG1 et IG2. Si votre pompe affiche la puissance
directement sur son écran (comme la AG1), votre contribution serait très
appréciée : notez la valeur affichée (en watts) à au minimum ces deux
paliers,

- **1150 RPM** (minimum)
- **3450 RPM** (maximum)

et idéalement aux mêmes RPM intermédiaires déjà mesurés pour la AG1
(1500, 2000, 2450 et 2850 RPM), pour une interpolation aussi précise que
celle de la AG1. Ouvrez une [issue GitHub](https://github.com/alray31/gopool-pump/issues)
avec le modèle exact de votre pompe et vos mesures (RPM → watts), et
j'ajouterai la courbe de calibration correspondante — aucune
réinstallation ne sera nécessaire de votre côté, juste une mise à jour
via HACS.

Les retours, rapports de bogue et suggestions sont aussi les bienvenus
via les mêmes [issues GitHub](https://github.com/alray31/gopool-pump/issues)
de ce dépôt.

### Marque de commerce

GoPool et GoPiscine sont des marques de commerce appartenant à leurs
propriétaires respectifs. Leur usage ici (nom, logo) est un usage
nominatif (« fair use ») à des fins d'identification uniquement, dans un
contexte strictement non commercial — cette intégration est un logiciel
libre et gratuit. Ce projet n'est ni affilié, ni approuvé, ni sponsorisé
par GoPool / GoPiscine, et ne cherche en aucune façon à générer un revenu
à partir de cette marque de commerce.

### Licence

Voir [LICENSE](LICENSE).

---

## English

[HACS](https://hacs.xyz/) integration to control a **GoPool / GoPiscine
AG1, IG1, or IG2** variable-speed pool pump in Home Assistant — fully
local once configured.

### Why this integration

These pumps use a Tuya Wi-Fi chip. Until now, controlling them in Home
Assistant meant going through localTuya and retrieving the `device_id`
and `local_key` yourself via a Tuya IoT developer account — a technical
and tedious step for a new user. This integration automates that
retrieval through a simple (QR-code) connection to your Smart Life /
Tuya Smart account, then runs entirely locally afterward, just like
localTuya.

### Prerequisites

- Your pump must already be added to the **Smart Life** app (or Tuya
  Smart), as described in the instruction manual that came with the
  pump.
- Your pump must be connected to your local network over Wi-Fi and be on
  the same subnet as Home Assistant. For example, if your Home Assistant
  instance is at `192.168.1.2`, your pump's IP address must start with
  `192.168.1.x`.
- Know your pump's IP address (for example via your Wi-Fi router's admin
  page). Assigning it a static IP address is strongly recommended — if
  the pump's IP address changes later, you'll need to reconfigure this
  integration.
- Have your phone or tablet with the **Smart Life** app (or Tuya Smart)
  within reach while setting up this integration.
- Home Assistant 2024.8.0 or newer.
- [HACS](https://hacs.xyz/) installed.

### Installation

This integration isn't (yet) in HACS's default store — add it as a
custom repository:

1. HACS → (⋮) menu in the top right → **Custom repositories**.
2. URL: `https://github.com/alray31/gopool-pump`, category **Integration**.
3. Search for "GoPool Variable Speed Pump" in HACS and install it.
4. Restart Home Assistant.

### Configuration

Settings → Devices & services → Add integration → **GoPool Variable
Speed Pump**. The config flow walks you through 3 steps:

1. **Link your account** — enter your Smart Life app's user code
   (Profile → Settings → Account and Security → User Code).
2. **Scan the QR code** shown, using the Smart Life app.
3. **Select your pump** from the list of linked devices, and confirm its
   local IP address.

Each step has its own detailed explanations (with animated screen
captures) built right into the interface — no need to repeat them here.

> **⚠️ Important:** this Smart Life cloud connection step is only needed
> once, to automatically retrieve the pump's local credentials.
> Afterward, the integration never talks to the cloud again. You can
> safely delete the Smart Life app from your phone if you'd like — but
> **never remove the pump from your Smart Life account**: doing so would
> change its `local_key` and require you to reconfigure the integration.

### Entities created

| Type | Entity |
|---|---|
| `switch` (control) | Power, Quick Clean |
| `switch` (configuration) | No Load Protection |
| `number` (control) | Pump Speed |
| `number` (configuration) | Quick Clean Speed, Quick Clean Duration, Timeout Duration, Stage 1-4 Speed, Stage 1-4 Duration |
| `select` (configuration) | Stage 1-4 Start Time (hour + minute combined into a single picker, restricted to the 10-minute steps the pump accepts) |
| `sensor` | Power Draw (W), Energy (kWh) — calculated from the commanded RPM and the pump model chosen during setup (see [Contributing](#contributing) for IG1/IG2) |

Only data points (DPs) confirmed to work locally on these pumps are
exposed — dead DPs (fault, schedule, motor_operation_state, etc.) are
intentionally excluded.

### How it works technically

- **Local communication** via [tinytuya](https://github.com/jasonacox/tinytuya),
  Tuya protocol version 3.5 (the only version confirmed on this pump
  line — fixed, not a choice made during setup).
- **Credential retrieval** via [tuya-device-sharing-sdk](https://pypi.org/project/tuya-device-sharing-sdk/),
  the same mechanism Home Assistant's own official Tuya integration uses
  for its own QR login, reusing Home Assistant's public client ID
  (`HA_3y9q4ak7g4ephrvke`) — not a secret belonging to this project, and
  no need to create a Tuya IoT developer account.
- Local polling every 3 seconds keeps state up to date, with automatic
  reconnection on a one-off failure — even on a failed poll, entities keep
  their last known value instead of going unavailable.
- The **Power Draw** (W) and **Energy** (kWh) sensors are computed
  directly by the integration (interpolating an RPM→W curve, then
  trapezoidal integration over time) — no HA template or helper needed.

### Known limitations

- The QR login mechanism reuses a client identifier that belongs to Home
  Assistant. This works today (confirmed by the community), but Tuya
  could restrict this third-party usage at some point without notice.
- Tested on the GoPool AG1; IG1/IG2 DPs are presumed identical but not
  yet confirmed in the field.
- The Power Draw / Energy sensors show as **unavailable** on IG1 and
  IG2: an RPM→W calibration curve currently exists only for the AG1 (see
  [Contributing](#contributing) below).

### Local connection issues

If the pump is unreachable after setup:

- Confirm the pump and Home Assistant are on the same subnet
  (especially if the pump is behind a Wi-Fi bridge/extender).
- Confirm port 6668 isn't blocked by a firewall or VLAN isolation
  between the two devices.
- Remove and re-add the integration through the config flow — if the
  pump was removed and re-added in Smart Life in the meantime, its
  `local_key` has changed.

### Contributing

**Do you own an IG1 or IG2 pump?** The **Power Draw** (W) and **Energy**
(kWh) sensors rely on an RPM → Watts calibration curve measured directly
on a real pump. Right now, only the **AG1** curve is available, so these
two sensors show as "unavailable" on IG1 and IG2. If your pump displays
its power draw directly on its screen (like the AG1 does), your
contribution would be very welcome: note down the displayed value (in
watts) at least at these two points,

- **1150 RPM** (minimum)
- **3450 RPM** (maximum)

and ideally at the same intermediate RPM steps already measured for the
AG1 (1500, 2000, 2450, and 2850 RPM), for interpolation as accurate as
the AG1's. Open a [GitHub issue](https://github.com/alray31/gopool-pump/issues)
with your pump's exact model and your measurements (RPM → watts), and
I'll add the matching calibration curve — no reinstall needed on your
end, just a HACS update.

Feedback, bug reports, and suggestions are also welcome via the same
[GitHub issues](https://github.com/alray31/gopool-pump/issues) for this
repository.

### Trademark notice

GoPool and GoPiscine are trademarks belonging to their respective
owners. Their use here (name, logo) is nominative use ("fair use") for
identification purposes only, in a strictly non-commercial context —
this integration is free, open-source software. This project is not
affiliated with, endorsed by, or sponsored by GoPool / GoPiscine, and
does not seek to generate any revenue from this trademark in any way.

### License

See [LICENSE](LICENSE).
