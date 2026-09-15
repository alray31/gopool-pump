"""Sensor platform for GoPool Variable Speed Pump.

Two native sensors, computed directly in Python from the pump's RPM->W
calibration curve (see RPM_POWER_TABLES in const.py) — no HA template or
"Riemann sum integral" helper required:

- Power Draw (W): instantaneous, piecewise-linear-interpolated from the
  commanded RPM (DP 103), 0 W when the pump is off.
- Energy (kWh): cumulative, trapezoidal-integrated in Python on every
  coordinator update, restored across restarts via RestoreEntity.

Both are "unavailable" for a pump model that has no calibrated curve yet
(currently IG1 / IG2) — see the note in const.py.
"""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import GoPoolCoordinator, device_info
from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PUMP_MODEL,
    DEFAULT_PUMP_MODEL,
    DOMAIN,
    DP_POWER_SWITCH,
    DP_PUMP_SPEED,
    RPM_POWER_TABLES,
)
from .logic import interpolate_rpm_to_watts

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GoPoolPowerSensor(coordinator, entry),
            GoPoolEnergySensor(coordinator, entry),
            GoPoolDeviceIdSensor(coordinator, entry),
            GoPoolLocalKeySensor(coordinator, entry),
            GoPoolIpAddressSensor(coordinator, entry),
        ]
    )


def _current_power_w(coordinator: GoPoolCoordinator, table: list[tuple[int, int]]) -> float:
    if not coordinator.data.get(DP_POWER_SWITCH):
        return 0.0
    rpm = coordinator.data.get(DP_PUMP_SPEED)
    if rpm is None:
        return 0.0
    return interpolate_rpm_to_watts(float(rpm), table)


class GoPoolPowerSensor(CoordinatorEntity[GoPoolCoordinator], SensorEntity):
    """Instantaneous power draw, interpolated from the RPM->W curve."""

    _attr_has_entity_name = True
    _attr_name = "Power Draw"
    _attr_icon = "mdi:flash"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._model = entry.options.get(
            CONF_PUMP_MODEL, entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL)
        )
        self._table = RPM_POWER_TABLES.get(self._model)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_power_draw"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def available(self) -> bool:
        return super().available and self._table is not None

    @property
    def native_value(self) -> float | None:
        if self._table is None:
            return None
        return round(_current_power_w(self.coordinator, self._table), 1)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self._table is None:
            return {
                "pump_model": self._model,
                "reason": "no calibrated RPM→W curve yet for this model",
            }
        return {"pump_model": self._model}


class GoPoolDeviceIdSensor(CoordinatorEntity[GoPoolCoordinator], SensorEntity):
    """Tuya device_id as its own diagnostic entity.

    Disabled by default (_attr_entity_registry_enabled_default = False): it
    isn't secret, but it's still identifying/setup-only data most users
    never need as a live entity, and leaving it off by default means
    nothing here writes to the recorder unless someone deliberately enables
    it (Settings -> Devices & services -> entity -> enable). Same reasoning
    as GoPoolLocalKeySensor below, just a lower-stakes value.
    """

    _attr_has_entity_name = True
    _attr_name = "Device ID"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._value = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_device_id"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def native_value(self) -> str:
        return self._value


class GoPoolLocalKeySensor(CoordinatorEntity[GoPoolCoordinator], SensorEntity):
    """Tuya local_key as its own diagnostic entity — disabled by default.

    local_key is a credential: an entity state is written to the recorder,
    shows up in the logbook, and can sync to a companion app, none of which
    is a good place for a credential to sit indefinitely. Disabled by
    default means it's opt-in (Settings -> Devices & services -> entity ->
    enable) rather than something every installer gets whether they want it
    or not. It's also reachable without enabling anything, via "Download
    diagnostics" (diagnostics.py) — that download isn't persisted anywhere
    either, it's generated fresh each time.
    """

    _attr_has_entity_name = True
    _attr_name = "Local Key"
    _attr_icon = "mdi:key"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._value = entry.data.get(CONF_LOCAL_KEY, "")
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_local_key"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def native_value(self) -> str:
        return self._value


class GoPoolIpAddressSensor(CoordinatorEntity[GoPoolCoordinator], SensorEntity):
    """Static LAN IP, as its own diagnostic entity — enabled by default.

    Unlike device_id/local_key, the IP is what you'd actually want handy
    day-to-day (opening the pump's local web UI, debugging connectivity),
    it's not a credential, and it's already visible without enabling
    anything via the device card's "Visit" link (configuration_url, see
    device_info()) — this is just a more explicit way to read the same
    value as a plain sensor state.
    """

    _attr_has_entity_name = True
    _attr_name = "IP Address"
    _attr_icon = "mdi:ip-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._value = entry.data.get("ip", "")
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_ip_address"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def native_value(self) -> str:
        return self._value


class GoPoolEnergySensor(CoordinatorEntity[GoPoolCoordinator], RestoreEntity, SensorEntity):
    """Cumulative energy, trapezoidal-integrated from the power curve.

    Integration happens once per coordinator update (in
    _handle_coordinator_update, not in the native_value property, so
    repeated state reads between updates never double-count) and survives
    HA restarts via RestoreEntity.
    """

    _attr_has_entity_name = True
    _attr_name = "Energy"
    _attr_icon = "mdi:lightning-bolt"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._model = entry.options.get(
            CONF_PUMP_MODEL, entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL)
        )
        self._table = RPM_POWER_TABLES.get(self._model)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_energy"
        self._attr_device_info = device_info(coordinator.hass, entry)
        self._total_kwh: float = 0.0
        self._last_power_w: float | None = None
        self._last_ts: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._total_kwh = float(last_state.state)
            except ValueError:
                self._total_kwh = 0.0
        # Baseline the clock now rather than at the last-seen timestamp —
        # otherwise the gap while HA was stopped would be integrated at
        # whatever power level happened to be reported first after restart.
        self._last_ts = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._integrate()
        super()._handle_coordinator_update()

    def _integrate(self) -> None:
        if self._table is None:
            return
        now = dt_util.utcnow()
        power_w = _current_power_w(self.coordinator, self._table)
        if self._last_ts is not None and self._last_power_w is not None:
            elapsed_hours = (now - self._last_ts).total_seconds() / 3600
            avg_w = (power_w + self._last_power_w) / 2
            self._total_kwh += (avg_w * elapsed_hours) / 1000
        self._last_power_w = power_w
        self._last_ts = now

    @property
    def available(self) -> bool:
        return super().available and self._table is not None

    @property
    def native_value(self) -> float | None:
        if self._table is None:
            return None
        return round(self._total_kwh, 4)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self._table is None:
            return {
                "pump_model": self._model,
                "reason": "no calibrated RPM→W curve yet for this model",
            }
        return {"pump_model": self._model}
