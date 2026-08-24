🇫🇷 [Version française](README.md)

# GoPool Variable Speed Pump

[HACS](https://hacs.xyz/) integration to control a **GoPool / GoPiscine
AG1, IG1, or IG2** variable-speed pool pump in Home Assistant — fully
local once configured.

## Why this integration

These pumps use a Tuya Wi-Fi chip. Until now, controlling them in Home
Assistant meant going through localTuya and retrieving the `device_id`
and `local_key` yourself via a Tuya IoT developer account — a technical
and tedious step for a new user. This integration automates that
retrieval through a simple (QR-code) connection to your Smart Life /
Tuya Smart account, then runs entirely locally afterward, just like
localTuya.

## Prerequisites

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

## Installation

This integration isn't (yet) in HACS's default store — add it as a
custom repository:

1. HACS → (⋮) menu in the top right → **Custom repositories**.
2. URL: `https://github.com/alray31/gopool-pump`, category **Integration**.
3. Search for "GoPool Variable Speed Pump" in HACS and install it.
4. Restart Home Assistant.

## Configuration

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

## Entities created

| Type | Entity |
|---|---|
| `switch` | Power, Quick Clean, No Load Protection |
| `number` | Current Speed, Quick Clean Speed, Quick Clean Duration, Timeout Duration, Stage 1-4 Speed, Stage 1-4 Duration |
| `time` | Stage 1-4 Start Time (hour + minute combined into a single picker) |

Only data points (DPs) confirmed to work locally on these pumps are
exposed — dead DPs (fault, schedule, motor_operation_state, etc.) are
intentionally excluded.

## How it works technically

- **Local communication** via [tinytuya](https://github.com/jasonacox/tinytuya),
  Tuya protocol version 3.5 (the only version confirmed on this pump
  line — fixed, not a choice made during setup).
- **Credential retrieval** via [tuya-device-sharing-sdk](https://pypi.org/project/tuya-device-sharing-sdk/),
  the same mechanism Home Assistant's own official Tuya integration uses
  for its own QR login, reusing Home Assistant's public client ID
  (`HA_3y9q4ak7g4ephrvke`) — not a secret belonging to this project, and
  no need to create a Tuya IoT developer account.
- Local polling every 30 seconds keeps state up to date.

## Known limitations

- The QR login mechanism reuses a client identifier that belongs to Home
  Assistant. This works today (confirmed by the community), but Tuya
  could restrict this third-party usage at some point without notice.
- Tested on the GoPool AG1; IG1/IG2 DPs are presumed identical but not
  yet confirmed in the field.

## Local connection issues

If the pump is unreachable after setup:

- Confirm the pump and Home Assistant are on the same subnet
  (especially if the pump is behind a Wi-Fi bridge/extender).
- Confirm port 6668 isn't blocked by a firewall or VLAN isolation
  between the two devices.
- Remove and re-add the integration through the config flow — if the
  pump was removed and re-added in Smart Life in the meantime, its
  `local_key` has changed.

## Contributing

Feedback, bug reports, and suggestions are welcome via this repository's
[GitHub issues](https://github.com/alray31/gopool-pump/issues).

## License

See [LICENSE](LICENSE).
