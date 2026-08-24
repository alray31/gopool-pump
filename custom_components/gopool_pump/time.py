"""Time platform for GoPool Variable Speed Pump.

Combines each stage's separate start_hour (0-23, step 1) and start_minute
(0/10/20/30/40/50, step 10) DPs into a single HH:MM time-picker entity —
nicer to use than two separate number entities. The pump's minute DP only
accepts 10-minute increments, so whatever minute the user picks is rounded
down to the nearest valid one before being written.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator
from .const import CONF_DEVICE_ID, DOMAIN, STAGE_START_TIME_DPS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GoPoolStageStartTime(coordinator, entry, stage, dps)
        for stage, dps in STAGE_START_TIME_DPS.items()
    ]
    async_add_entities(entities)


class GoPoolStageStartTime(CoordinatorEntity[GoPoolCoordinator], TimeEntity):
    """Combined start hour + start minute for one pump stage."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: GoPoolCoordinator, entry: ConfigEntry, stage: int, dps: dict[str, str]
    ) -> None:
        super().__init__(coordinator)
        self._hour_dp = dps["start_hour"]
        self._minute_dp = dps["start_minute"]
        self._attr_name = f"Stage {stage} Start Time"
        self._attr_icon = "mdi:clock-start"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_stage_{stage}_start_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.data.get("name", "GoPool Pump"),
            manufacturer="GoPiscine",
        )

    @property
    def native_value(self) -> time | None:
        hour = self.coordinator.data.get(self._hour_dp)
        minute = self.coordinator.data.get(self._minute_dp)
        if hour is None or minute is None:
            return None
        return time(hour=int(hour), minute=int(minute))

    async def async_set_value(self, value: time) -> None:
        # The pump only accepts minute values in steps of 10 — round down
        # to the nearest valid one rather than rejecting the input.
        rounded_minute = (value.minute // 10) * 10
        await self.coordinator.async_write_dps(
            {self._hour_dp: value.hour, self._minute_dp: rounded_minute}
        )
