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

DEFAULT_PROTOCOL_VERSION = "3.5"
DEFAULT_SCAN_INTERVAL = 30  # seconds — local polling, cheap and fast over LAN

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
# any time without notice. The manual entry path (device_id + local_key)
# always remains available as a fallback and has zero dependency on this.
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
        "name": "Current Speed",
        "unit": "rpm",
        "min": 1150,
        "max": 3450,
        "step": 50,
        "icon": "mdi:speedometer",
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
    },
    "102": {
        "platform": "switch",
        "key": "schedule",
        "name": "Schedule",
        "icon": "mdi:calendar-clock",
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
    }
    DP_MAP[_dps["start_hour"]] = {
        "platform": "number",
        "key": f"stage_{_stage}_start_hour",
        "name": f"Stage {_stage} Start Hour",
        "unit": "h",
        "min": 0,
        "max": 23,
        "step": 1,
        "icon": "mdi:clock-start",
    }
    DP_MAP[_dps["start_minute"]] = {
        "platform": "number",
        "key": f"stage_{_stage}_start_minute",
        "name": f"Stage {_stage} Start Minute",
        "unit": "min",
        "min": 0,
        "max": 50,
        "step": 10,
        "icon": "mdi:clock-time-eight",
    }

del _stage, _dps
