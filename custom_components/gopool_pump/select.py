"""Select platform for GoPool Variable Speed Pump.

Stage 1-4 start time is exposed as a single combined entity per stage, but
as a dropdown of exact "HH:MM" strings rather than a free-form time picker.
The pump only accepts minute values in steps of 10 (0/10/20/30/40/50) —
localTuya and the Smart Life app both silently reject anything else, and a
free-form TimeEntity here previously had to silently round down to the
nearest 10, which was confusing. A restricted dropdown makes an invalid
value impossible to pick in the first place.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator
from .const import CONF_DEVICE_ID, DOMAIN, STAGE_START_TIME_DPS

_MINUTE_STEPS = (0, 10, 20, 30, 40, 50)
_OPTIONS = [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in _MINUTE_STEPS]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the stage start-time select entities."""
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GoPoolStageStartTime(coordinator, entry, stage, dps)
        for stage, dps in STAGE_START_TIME_DPS.items()
    ]
    async_add_entities(entities)


class GoPoolStageStartTime(CoordinatorEntity[GoPoolCoordinator], SelectEntity):
    """Combined start-time dropdown for one stage (hour DP + minute DP)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = _OPTIONS

    def __init__(
        self,
        coordinator: GoPoolCoordinator,
        entry: ConfigEntry,
        stage: int,
        dps: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        self._hour_dp = dps["start_hour"]
        self._minute_dp = dps["start_minute"]
        self._attr_name = f"Stage {stage} Start Time"
        self._attr_icon = "mdi:clock-start"
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_stage_{stage}_start_time_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.data.get("name", "GoPool Pump"),
            manufacturer="GoPiscine",
        )

    @property
    def current_option(self) -> str | None:
        hour = self.coordinator.data.get(self._hour_dp)
        minute = self.coordinator.data.get(self._minute_dp)
        if hour is None or minute is None:
            return None
        # Snap to the nearest step in case the pump ever reports an
        # off-grid value (e.g. set by another client) so the UI never
        # shows a selection outside the fixed option list.
        snapped_minute = (int(minute) // 10) * 10
        return f"{int(hour):02d}:{snapped_minute:02d}"

    async def async_select_option(self, option: str) -> None:
        hour_str, minute_str = option.split(":")
        await self.coordinator.async_write_dps(
            {self._hour_dp: int(hour_str), self._minute_dp: int(minute_str)}
        )
