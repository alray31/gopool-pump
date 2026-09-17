"""Constants for the GoPool Variable Speed Pump integration.

DP map hardcoded from the empirically-confirmed-functional DPs documented in
this project's README (only DPs that actually work over the local protocol
on this pump's firmware are listed here — the dead ones, fault/schedule_status/
motor_operation_state/etc., are intentionally excluded, same as the localtuya
template this integration replaces).
"""

from __future__ import annotations

DOMAIN = "gopool_pump"

# --------------------------------------------------------------------------
# Config entry keys
# --------------------------------------------------------------------------
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_USER_CODE = "user_code"
CONF_PUMP_MODEL = "pump_model"

# Used only to pick the right RPM->W calibration curve (see RPM_POWER_TABLES
# below) for the Power Draw / Energy sensors — has no effect on control.
PUMP_MODELS = ["AG1", "IG1", "IG2"]
DEFAULT_PUMP_MODEL = "AG1"

# What each model code actually is, in plain terms — used both on the
# device info card and in the config/options flow's "Pump model" selector
# (see pump_model_label() in __init__.py, used by the DeviceInfo card's
# "model" field). Plain Python dict, not an HA selector translation,
# because that field is server-rendered with no per-viewer translation
# mechanism at all in Home Assistant — this always follows
# hass.config.language (the server's single configured language), no way
# around it. Config-flow SELECTORS don't have that limitation and now go
# through HA's own translation_key mechanism instead — see
# PUMP_MODEL_SLUGS below and _pump_model_selector() in config_flow.py.
#
# Only the languages pump_model_label() actually resolves to are useful
# here (see its language -> dict-key mapping) — adding a language to one
# without the other is a silent no-op, so keep them in sync.
PUMP_MODEL_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "AG1": {
        "en": "Above-ground pool, 1.5 HP",
        "fr": "Piscine hors-terre 1.5 HP",
        "es": "Piscina sobre el suelo, 1.5 HP",
        "zh": "地上泳池，1.5 HP",
    },
    "IG1": {
        "en": "In-ground pool, 1.65 HP",
        "fr": "Piscine creusée 1.65 HP",
        "es": "Piscina enterrada, 1.65 HP",
        "zh": "地埋泳池，1.65 HP",
    },
    "IG2": {
        "en": "In-ground pool, 2.2 HP",
        "fr": "Piscine creusée 2.2 HP",
        "es": "Piscina enterrada, 2.2 HP",
        "zh": "地埋泳池，2.2 HP",
    },
}

# Lowercase stand-ins for PUMP_MODELS' real (uppercase) values, used ONLY
# by config_flow.py's _pump_model_selector() for its widget options. HA's
# translation_key selector mechanism (which resolves option labels
# per-VIEWER, unlike PUMP_MODEL_DESCRIPTIONS above) requires every option
# VALUE to itself be a valid translation key ([a-z0-9-_]+, no uppercase),
# and hassfest rejects "AG1"/"IG1"/"IG2" outright. The config entry's
# actual stored CONF_PUMP_MODEL value is NEVER the slug — config_flow.py
# converts back via PUMP_MODEL_SLUGS_REVERSE the moment a submitted form
# is read, so this exists purely as an implementation detail of that one
# selector, invisible everywhere else (no data migration needed).
PUMP_MODEL_SLUGS: dict[str, str] = {"AG1": "ag1", "IG1": "ig1", "IG2": "ig2"}
PUMP_MODEL_SLUGS_REVERSE: dict[str, str] = {slug: model for model, slug in PUMP_MODEL_SLUGS.items()}

# Fixed, not user-selectable: every GoPool AG1/IG1/IG2 pump confirmed so far
# uses local protocol 3.5. Still stored per config entry (not hardcoded at
# the call sites) so a future pump generation needing a different version
# wouldn't require a data migration.
DEFAULT_PROTOCOL_VERSION = "3.5"
DEFAULT_SCAN_INTERVAL = 3  # seconds. A raw TCP connect measured 0.06s once
# dev_type="device22" was removed, so status() responds quickly — and since
# _async_update_data now falls back to the last known state instead of
# raising on a failed poll (see __init__.py), a transient miss at this rate
# is invisible to the user rather than a visible availability flicker. If
# the pump's wifi module ever struggles under this polling rate, raise this
# back up before anything else.

# --------------------------------------------------------------------------
# Tuya Cloud "QR login" constants — REUSED from Home Assistant's own public,
# officially-registered partner app identifiers (visible in HA core's own
# open-source repo: homeassistant/components/tuya/const.py). This is the
# same mechanism used by community tools such as vineetchoudhary/tuya-local-key
# to retrieve device credentials without creating a Tuya IoT Developer
# project. It is NOT a secret Anthropic/GoPool-issued credential — it is
# Home Assistant's own public "haauthorize" schema identifier.
#
# ⚠️ Caveat: this is a third-party reuse of an identifier Tuya issued to
# Home Assistant specifically. It works today (community reports confirm
# it), but Tuya could rate-limit or revoke it for non-HA-core consumers at
# any time without notice — setup is entirely QR-based (see config_flow.py),
# so that would break new installs until this identifier is updated.
# --------------------------------------------------------------------------
TUYA_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
TUYA_SCHEMA = "haauthorize"

TUYA_RESPONSE_SUCCESS = "success"
TUYA_RESPONSE_RESULT = "result"
TUYA_RESPONSE_QR_CODE = "qrcode"
TUYA_RESPONSE_CODE = "code"
TUYA_RESPONSE_MSG = "msg"

# --------------------------------------------------------------------------
# Auto-advancing QR login (config_flow.py's async_step_scan /
# __wait_for_scan): a background task polls login_result() instead of
# waiting for a manual Submit click.
# --------------------------------------------------------------------------
TUYA_QR_POLL_INTERVAL = 3  # seconds between login_result() checks.
TUYA_QR_REFRESH_AFTER = 90  # seconds of no confirmation before silently
# issuing a fresh QR code. Tuya does not document a fixed token lifetime,
# but community tooling built on the same SDK (vineetchoudhary/
# tuya-local-key) reports it "expires within a minute or two" empirically —
# this stays comfortably under that so the user is never shown a hard
# "QR expired" error, the code just quietly changes underneath them.
TUYA_QR_MAX_CONSECUTIVE_ERRORS = 5  # consecutive *transport* failures
# (network/API errors talking to Tuya, NOT a plain "not scanned yet"
# response) before giving up instead of retrying forever.

# --------------------------------------------------------------------------
# Background IP self-healing (GoPoolCoordinator._maybe_heal_ip,
# __init__.py): when the pump's LAN IP changes (no static IP assigned —
# see the README), local polling starts failing with a plain connectivity
# error, not the local_key rejection that triggers reauth. Rather than
# staying stuck until the user manually fixes it (via the "Reconfigure"
# flow, async_step_reconfigure in config_flow.py), the coordinator tries
# the same passive LAN scan setup uses (discovery.py) on its own first —
# see should_attempt_ip_rescan() in logic.py for exactly when.
# --------------------------------------------------------------------------
TUYA_IP_RESCAN_AFTER_FAILURES = 10  # consecutive failed POLL CYCLES (each
# cycle already retries once internally, see _async_update_data) before
# attempting a rescan — at the default 3s poll interval that's ~30s of
# being unreachable, comfortably past a one-off wifi blip.
TUYA_IP_RESCAN_COOLDOWN = 300  # seconds between rescan attempts once
# should_attempt_ip_rescan() starts returning True for a given entry — an
# extended outage (pump powered off, real network down) must not
# re-trigger a scan on every single poll cycle forever.

# --------------------------------------------------------------------------
# Config flow URLs (GIFs, links to project pages). HA's translation linter
# (hassfest) rejects a raw URL embedded directly in a translation string —
# it must be passed as a description_placeholder instead, with the string
# itself only holding a "{placeholder}" token (see config_flow.py, which
# merges these into every relevant step's description_placeholders dict).
# --------------------------------------------------------------------------
USER_CODE_GIF_URL = "https://raw.githubusercontent.com/alray31/gopool-pump/main/docs/images/user_code.gif"
QR_SCAN_GIF_URL = "https://raw.githubusercontent.com/alray31/gopool-pump/main/docs/images/qr_scan.gif"
PUMP_DISCUSSIONS_URL = "https://github.com/alray31/gopool-pump/discussions"

# --------------------------------------------------------------------------
# DP map: dp_id (str, as used by tinytuya's status() dict) -> entity spec.
# platform: "switch" | "number"
# category: omitted -> primary control (shown at the top of the device
#   page); "config" -> secondary/configuration entity (shown collapsed
#   under "Configuration"). Only the 3 entities the user actually
#   interacts with day-to-day (Power, Pump Speed, Quick Clean) are
#   controls — everything else is setup/tuning.
# --------------------------------------------------------------------------
# Named separately from DP_MAP's string keys because sensor.py also needs
# them directly (to read the power switch state / commanded RPM when
# computing the Power Draw and Energy sensors).
DP_POWER_SWITCH = "1"
DP_PUMP_SPEED = "103"

DP_MAP: dict[str, dict] = {
    # Power
    DP_POWER_SWITCH: {
        "platform": "switch",
        "key": "power",
        "name": "Power",
        "icon": "mdi:pump",
    },
    # Current / commanded speed — DP103 actually controls the speed despite
    # its "current" name (confirmed empirically, see README).
    DP_PUMP_SPEED: {
        "platform": "number",
        "key": "current_speed",
        "name": "Pump Speed",
        "unit": "rpm",
        "min": 1000,
        "max": 3450,
        "step": 50,
        "icon": "mdi:speedometer",
        "mode": "slider",
    },
    "189": {
        "platform": "switch",
        "key": "quick_clean",
        "name": "Quick Clean",
        "icon": "mdi:broom",
    },
    "190": {
        "platform": "number",
        "key": "quick_clean_speed",
        "name": "Quick Clean Speed",
        "unit": "rpm",
        "min": 1000,
        "max": 3450,
        "step": 10,
        "icon": "mdi:speedometer",
        "category": "config",
    },
    "191": {
        "platform": "number",
        "key": "quick_clean_duration",
        "name": "Quick Clean Duration",
        "unit": "min",
        "min": 10,
        "max": 600,
        "step": 10,
        "icon": "mdi:camera-timer",
        "category": "config",
    },
    "106": {
        "platform": "switch",
        "key": "no_load_protection",
        "name": "No Load Protection",
        "icon": "mdi:shield-check",
        "category": "config",
    },
    "188": {
        "platform": "number",
        "key": "timeout_duration",
        "name": "Timeout Duration",
        "unit": "min",
        "min": 1,
        "max": 600,
        "step": 1,
        "icon": "mdi:timer-sand",
        "category": "config",
    },
}

# Stage 1-4 speed / duration / start hour / start minute — generated to
# avoid repeating the same block four times.
_STAGE_DP_IDS = {
    1: {"speed": "149", "duration": "151", "start_hour": "141", "start_minute": "142"},
    2: {"speed": "152", "duration": "154", "start_hour": "143", "start_minute": "144"},
    3: {"speed": "155", "duration": "157", "start_hour": "145", "start_minute": "146"},
    4: {"speed": "158", "duration": "160", "start_hour": "147", "start_minute": "148"},
}

for _stage, _dps in _STAGE_DP_IDS.items():
    DP_MAP[_dps["speed"]] = {
        "platform": "number",
        "key": f"stage_{_stage}_speed",
        "name": f"Stage {_stage} Speed",
        "unit": "rpm",
        "min": 1000,
        "max": 3450,
        "step": 50,
        "icon": "mdi:speedometer",
        "category": "config",
    }
    DP_MAP[_dps["duration"]] = {
        "platform": "number",
        "key": f"stage_{_stage}_duration",
        "name": f"Stage {_stage} Duration",
        "unit": "h",
        "min": 0,
        "max": 24,
        "step": 1,
        "icon": "mdi:camera-timer",
        "category": "config",
    }
    # start_hour / start_minute are intentionally NOT added to DP_MAP as
    # separate number entities — the select.py platform combines them into
    # one HH:MM entity per stage instead (see STAGE_START_TIME_DPS below).

del _stage, _dps

# --------------------------------------------------------------------------
# Stage 1-4 combined start-time entities (select.py): each maps to two DPs —
# an hour (0-23, step 1) and a minute (0/10/20/.../50, step 10) — exposed as
# a single dropdown of exact "HH:MM" strings instead of a free-form time
# picker, so the user can never select a minute value the pump rejects.
# --------------------------------------------------------------------------
STAGE_START_TIME_DPS: dict[int, dict[str, str]] = {
    stage: {"start_hour": dps["start_hour"], "start_minute": dps["start_minute"]}
    for stage, dps in _STAGE_DP_IDS.items()
}

# --------------------------------------------------------------------------
# RPM -> instantaneous power (W) calibration curve, per pump model. Used by
# sensor.py to compute a native "Power Draw" sensor (piecewise-linear
# interpolation between the points below) and, integrated over time in
# Python, a cumulative "Energy" sensor — no HA template or helper needed.
#
# AG1: measured directly on a real AG1 pump (6 real data points, see this
#   project's README for the methodology) — sensor.py interpolates between
#   them for the other 50 RPM steps.
# IG1 / IG2: no measurements yet. Deliberately left as None instead of
#   reusing the AG1 curve or guessing — the motor/impeller differ enough
#   between lines that a borrowed curve could be meaningfully wrong. The
#   Power Draw / Energy sensors report "unavailable" for these two models
#   until real RPM->W data is added here (just extend this dict — no other
#   code change needed).
# --------------------------------------------------------------------------
RPM_POWER_TABLES: dict[str, list[tuple[int, int]] | None] = {
    "AG1": [
        (1000, 37),
        (1150, 50),
        (1500, 83),
        (2000, 160),
        (2450, 271),
        (2850, 374),
        (3450, 637),
    ],
    "IG1": None,
    "IG2": None,
}
