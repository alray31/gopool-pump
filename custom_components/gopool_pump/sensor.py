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
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import GoPoolCoordinator
from .const import (
    CONF_DEVICE_ID,
    CONF_PUMP_MODEL,
    DEFAULT_PUMP_MODEL,
    DOMAIN,
    DP_POWER_SWITCH,
    DP_PUMP_SPEED,
    RPM_POWER_TABLES,
)

_LOGGER = logging.getLogger(__name__)


def _interpolate(rpm: float, table: list[tuple[int, int]]) -> float:
    """Piecewise-linear interpolation over an ascending (rpm, watts) table."""
    if rpm <= table[0][0]:
        return float(table[0][1])
    if rpm >= table[-1][0]:
        return float(table[-1][1])
    for (r1, w1), (r2, w2) in zip(table, table[1:]):
        if r1 <= rpm <= r2:
            ratio = (rpm - r1) / (r2 - r1)
            return w1 + ratio * (w2 - w1)
    return float(table[-1][1])  # pragma: no cover - unreachable, table covers the range


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
        name=entry.data.get("name", "GoPool Pump"),
        manufacturer="GoPiscine",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GoPoolPowerSensor(coordinator, entry),
            GoPoolEnergySensor(coordinator, entry),
        ]
    )


def _current_power_w(coordinator: GoPoolCoordinator, table: list[tuple[int, int]]) -> float:
    if not coordinator.data.get(DP_POWER_SWITCH):
        return 0.0
    rpm = coordinator.data.get(DP_PUMP_SPEED)
    if rpm is None:
        return 0.0
    return _interpolate(float(rpm), table)


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
        self._attr_device_info = _device_info(entry)

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
        self._attr_device_info = _device_info(entry)
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
