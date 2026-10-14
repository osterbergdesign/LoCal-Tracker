"""Sensors: what each person has eaten today, and today's planned meals."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MEAL_LABELS, MEALS

# key, name, unit, icon
PERSON_SENSORS = [
    ("kcal", "Calories eaten", "kcal", "mdi:food"),
    ("kcal_left", "Calories left", "kcal", "mdi:silverware-fork-knife"),
    ("protein", "Protein eaten", "g", "mdi:food-drumstick"),
    ("carbs", "Carbohydrates eaten", "g", "mdi:bread-slice"),
    ("fat", "Fat eaten", "g", "mdi:oil"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN]["coordinator"]
    known: set[int] = set()

    @callback
    def add_new_people() -> None:
        new = []
        for person in (coordinator.data or {}).get("users", []):
            if person["id"] in known:
                continue
            known.add(person["id"])
            new += [LoCalPersonSensor(coordinator, person, *spec) for spec in PERSON_SENSORS]
        if new:
            async_add_entities(new)

    async_add_entities([LoCalPlanSensor(coordinator, meal) for meal in MEALS])  # also creates the household device
    add_new_people()
    entry.async_on_unload(coordinator.async_add_listener(add_new_people))


def _household_device() -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, "household")}, name="LoCal", manufacturer="LoCal",
                      entry_type=DeviceEntryType.SERVICE, configuration_url="homeassistant://local-tracker")


class LoCalPersonSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, person: dict, key: str, name: str, unit: str, icon: str) -> None:
        super().__init__(coordinator)
        self._user_id = person["id"]
        self._key = key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_user{person['id']}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"user{person['id']}")}, name=f"LoCal {person['username']}",
            manufacturer="LoCal", model="Food diary", entry_type=DeviceEntryType.SERVICE,
            via_device=(DOMAIN, "household"))

    def _person(self) -> dict | None:
        for p in (self.coordinator.data or {}).get("users", []):
            if p["id"] == self._user_id:
                return p
        return None

    @property
    def available(self) -> bool:
        return super().available and self._person() is not None

    @property
    def native_value(self):
        p = self._person()
        return p.get(self._key) if p else None

    @property
    def extra_state_attributes(self):
        p = self._person()
        if not p:
            return None
        goal_key = {"kcal": "kcal_goal", "kcal_left": "kcal_goal", "protein": "protein_goal",
                    "carbs": "carbs_goal", "fat": "fat_goal"}[self._key]
        return {"goal": p.get(goal_key), "date": self.coordinator.data.get("date"), "entries_today": p.get("entries")}


class LoCalPlanSensor(CoordinatorEntity, SensorEntity):
    """Today's planned breakfast/lunch/dinner/snack from the shared meal plan."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-today"

    def __init__(self, coordinator, meal: str) -> None:
        super().__init__(coordinator)
        self._meal = meal
        self._attr_name = f"Planned {MEAL_LABELS[meal].lower()}"
        self._attr_unique_id = f"{DOMAIN}_planned_{meal}"
        self._attr_device_info = _household_device()

    def _items(self):
        return [p for p in (self.coordinator.data or {}).get("plan", []) if p["meal"] == self._meal]

    @property
    def native_value(self):
        items = self._items()
        return ", ".join(i["name"] for i in items)[:255] if items else "Nothing planned"

    @property
    def extra_state_attributes(self):
        return {"items": [{"name": i["name"], "grams": i["grams"], "kcal": i["kcal"], "note": i["note"]}
                          for i in self._items()],
                "kcal_per_person": sum(i["kcal"] for i in self._items())}
