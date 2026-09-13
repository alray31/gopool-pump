"""Diagnostics support for GoPool Variable Speed Pump.

Exposes device_id, local_key and IP via Home Assistant's standard
Settings -> Devices & services -> [device] -> "Download diagnostics" button,
plus the coordinator's current raw DP snapshot (handy for debugging a DP
that isn't in DP_MAP yet, or an entity showing a surprising value).

Unlike most core integrations (e.g. HA's own Tuya integration), local_key is
INTENTIONALLY NOT passed through `homeassistant.components.diagnostics.
async_redact_data` here — this project's user explicitly wants it visible
for convenient local troubleshooting rather than hidden behind a
"REDACTED" placeholder every time.

⚠️ If you're about to paste this file's output into a public GitHub issue
or forum post, redact "local_key" yourself first — anyone with it plus your
device_id and LAN access can control your pump locally.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import GoPoolCoordinator
from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_PUMP_MODEL,
    DEFAULT_PUMP_MODEL,
    DOMAIN,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "name": entry.data.get("name"),
            "device_id": entry.data.get(CONF_DEVICE_ID),
            "ip": entry.data.get("ip"),
            "local_key": entry.data.get(CONF_LOCAL_KEY),
            "protocol_version": entry.data.get(CONF_PROTOCOL_VERSION),
            "pump_model": entry.options.get(
                CONF_PUMP_MODEL, entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL)
            ),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "data": coordinator.data,
        },
    }
