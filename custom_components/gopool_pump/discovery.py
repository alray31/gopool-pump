"""Best-effort local network discovery for GoPool Variable Speed Pump
devices.

Shared between config_flow.py (pre-filling the "IP" field during initial
setup and during the manual "Reconfigure" flow — async_step_pick_device /
async_step_reconfigure) and __init__.py (GoPoolCoordinator's background
IP self-healing when the pump's stored IP stops responding — see
_maybe_heal_ip). Split out to its own module rather than living in
config_flow.py (where it originated) purely to avoid __init__.py needing
to import from config_flow.py, which already imports from __init__.py
(pump_model_label) — that would be a circular import.
"""

from __future__ import annotations

import logging

import tinytuya
import tinytuya.scanner  # noqa: F401 - needed so tinytuya.scanner.devices() (below) resolves;
# `import tinytuya` alone does NOT attach the scanner submodule as an
# attribute. Used directly rather than the tinytuya.deviceScan() wrapper
# because that wrapper never forwards `wantids`/`byID` through to
# scanner.devices() (checked against both the manifest's tinytuya>=1.13.0
# floor and the latest release — true in both).

_LOGGER = logging.getLogger(__name__)


def scan_for_lan_ips(device_ids: list[str]) -> dict[str, str]:
    """Passive UDP scan for each device's current LAN IP, keyed by
    device_id.

    Tuya devices broadcast their presence periodically over UDP (ports
    6666/6667/7000, handled entirely by tinytuya). Passing `wantids` makes
    tinytuya return as soon as every requested device has been heard from,
    rather than waiting out the full scan window — in practice this is
    usually a couple of seconds, not the ~18s a plain `python3 -m tinytuya
    scan` takes with nothing to look for. `forcescan=False` keeps this to
    passive listening only — no active IP-range sweep, no elevated
    permissions needed. `poll=False`: we only want the IP here, not a dps
    read (which would need the local_key wired in for no benefit at this
    stage).

    Never lets an exception escape, and "found nothing" is a normal,
    silent outcome — this is a convenience, not a requirement. It comes up
    empty when HA can't see LAN broadcast traffic at all (most commonly: a
    Docker container on bridge networking instead of host/macvlan), which
    every caller of this function is written to tolerate: config_flow.py
    falls back to a plain editable IP field, and GoPoolCoordinator's
    background self-healing (__init__.py) just keeps its existing
    "unreachable" behavior and tries again later.
    """
    try:
        # tinytuya.scanner.devices(), NOT the tinytuya.deviceScan()
        # wrapper — see the import comment at the top of this file for why.
        found = tinytuya.scanner.devices(
            verbose=False,
            scantime=8,
            poll=False,
            forcescan=False,
            byID=True,
            wantids=device_ids,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Local UDP scan for %r failed", device_ids, exc_info=True)
        return {}
    return {dev_id: info["ip"] for dev_id, info in found.items() if info.get("ip")}
