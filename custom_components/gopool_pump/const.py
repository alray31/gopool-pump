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

# Fixed, not user-selectable: every GoPool AG1/IG1/IG2 pump confirmed so far
# uses local protocol 3.5. Still stored per config entry (not hardcoded at
# the call sites) so a future pump generation needing a different version
# wouldn't require a data migration.
DEFAULT_PROTOCOL_VERSION = "3.5"
DEFAULT_SCAN_INTERVAL = 5  # seconds. The earlier "slow bridge" theory turned
# out to be wrong — once dev_type="device22" was removed, a raw TCP connect
# measured 0.06s and status() responds quickly, so external changes (the
# physical pump controls, the Smart Life app) now show up in HA within a
# few seconds instead of up to 30s. Combined with the retry-on-failure in
# __init__.py's _async_update_data, this should stay reliable — but if you
# ever see the pump's wifi module struggle under this polling rate, raise
# this back up before anything else.

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
# DP map: dp_id (str, as used by tinytuya's status() dict) -> entity spec.
# platform: "switch" | "number"
# category: omitted -> primary control (shown at the top of the device
#   page); "config" -> secondary/configuration entity (shown collapsed
#   under "Configuration"). Only the 4 entities the user actually
#   interacts with day-to-day (Power, Pump Speed, Quick Clean,
#   No Load Protection) are controls — everything else is setup/tuning.
# --------------------------------------------------------------------------
DP_MAP: dict[str, dict] = {
    # Power
    "1": {
        "platform": "switch",
        "key": "power",
        "name": "Power",
        "icon": "mdi:pump",
    },
    # Current / commanded speed — DP103 actually controls the speed despite
    # its "current" name (confirmed empirically, see README).
    "103": {
        "platform": "number",
        "key": "current_speed",
        "name": "Pump Speed",
        "unit": "rpm",
        "min": 1150,
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
    # separate number entities — the time.py platform combines them into
    # one HH:MM entity per stage instead (see STAGE_START_TIME_DPS below).

del _stage, _dps

# --------------------------------------------------------------------------
# Stage 1-4 combined start-time entities (time.py): each maps to two DPs —
# an hour (0-23, step 1) and a minute (0/10/20/.../50, step 10) — exposed
# as a single HH:MM time picker instead of two separate number entities.
# --------------------------------------------------------------------------
STAGE_START_TIME_DPS: dict[int, dict[str, str]] = {
    stage: {"start_hour": dps["start_hour"], "start_minute": dps["start_minute"]}
    for stage, dps in _STAGE_DP_IDS.items()
}
