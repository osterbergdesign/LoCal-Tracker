"""The shared meal plan as a Home Assistant calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MEAL_LABELS, MEAL_TIMES
from .sensor import _household_device


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([MatkollPlanCalendar(hass.data[DOMAIN]["coordinator"], hass.data[DOMAIN]["runner"])])


def _event(item: dict) -> CalendarEvent:
    hour, minute, length = MEAL_TIMES[item["meal"]]
    day = date.fromisoformat(item["date"])
    start = dt_util.start_of_local_day(day) + timedelta(hours=hour, minutes=minute)
    details = f"{round(item['grams'])} g per person · {item['kcal']} kcal"
    if item.get("note"):
        details += f"\n{item['note']}"
    return CalendarEvent(start=start, end=start + timedelta(minutes=length),
                         summary=f"{MEAL_LABELS[item['meal']]}: {item['name']}", description=details,
                         uid=f"matkoll-plan-{item['id']}")


class MatkollPlanCalendar(CoordinatorEntity, CalendarEntity):
    _attr_has_entity_name = True
    _attr_name = "Meal plan"
    _attr_icon = "mdi:calendar-heart"

    def __init__(self, coordinator, runner) -> None:
        super().__init__(coordinator)
        self._runner = runner
        self._attr_unique_id = f"{DOMAIN}_meal_plan"
        self._attr_device_info = _household_device()

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next planned meal today."""
        now = dt_util.now()
        events = sorted((_event(i) for i in (self.coordinator.data or {}).get("plan", [])), key=lambda e: e.start)
        for e in events:
            if e.end > now:
                return e
        return None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        start = dt_util.as_local(start_date).date().isoformat()
        end = dt_util.as_local(end_date).date().isoformat()
        items = await hass.async_add_executor_job(self._runner.call, "plan_range", start, end)
        return [e for e in (_event(i) for i in items) if e.end > start_date and e.start < end_date]
