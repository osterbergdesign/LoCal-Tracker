"""Matkoll: household meal planner and calorie tracker, running inside Home Assistant."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, MEALS, PANEL_URL, STATIC_URL
from .runner import MatkollRunner

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

LOG_FOOD_SCHEMA = vol.Schema({
    vol.Required("food"): cv.string,
    vol.Required("grams"): vol.All(vol.Coerce(float), vol.Range(min=0.1)),
    vol.Optional("meal"): vol.In(MEALS),
    vol.Optional("date"): cv.date,
    vol.Optional("person"): cv.entity_id,
})


def _version(hass: HomeAssistant) -> str:
    return hass.data.get(f"{DOMAIN}_version", "1")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data_dir = hass.config.path(DOMAIN)
    runner = MatkollRunner(data_dir)
    try:
        await hass.async_add_executor_job(runner.start)
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"Matkoll couldn't start: {err}") from err

    async def _update() -> dict[str, Any]:
        return await hass.async_add_executor_job(runner.call, "summary_all")

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name=DOMAIN, update_method=_update, update_interval=timedelta(seconds=60))
    hass.data[DOMAIN] = {"runner": runner, "coordinator": coordinator}
    await coordinator.async_config_entry_first_refresh()

    await _async_register_frontend(hass)
    _register_websocket(hass)
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        frontend.async_remove_panel(hass, PANEL_URL)
        for service in ("log_food", "sync_mealie"):
            hass.services.async_remove(DOMAIN, service)
        data = hass.data.pop(DOMAIN, None)
        if data:
            await hass.async_add_executor_job(data["runner"].stop)
    return unloaded


async def _async_register_frontend(hass: HomeAssistant) -> None:
    static_dir = os.path.join(os.path.dirname(__file__), "matkoll_app", "static")
    if not hass.data.get(f"{DOMAIN}_static"):
        # Static routes can't be removed again, so they're registered once per Home Assistant run.
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, static_dir, False)])
        hass.data[f"{DOMAIN}_static"] = True
        integration_version = await hass.async_add_executor_job(_read_version)
        hass.data[f"{DOMAIN}_version"] = integration_version
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="matkoll-panel",
        sidebar_title="Matkoll",
        sidebar_icon="mdi:food-apple",
        module_url=f"{STATIC_URL}/ha-panel.js?v={_version(hass)}",
        embed_iframe=False,
        require_admin=False,
    )


def _read_version() -> str:
    import json
    with open(os.path.join(os.path.dirname(__file__), "manifest.json"), encoding="utf-8") as f:
        return json.load(f).get("version", "1")


def _ha_user(user) -> dict[str, Any]:
    return {"id": user.id, "name": user.name or "Home Assistant user", "admin": user.is_admin}


@callback
def _register_websocket(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_ws"):
        return
    hass.data[f"{DOMAIN}_ws"] = True
    websocket_api.async_register_command(hass, ws_request)


@websocket_api.websocket_command({
    vol.Required("type"): "matkoll/request",
    vol.Required("method"): vol.In(["GET", "POST", "PUT", "DELETE"]),
    vol.Required("path"): vol.All(str, vol.Match(r"^/api/")),
    vol.Optional("body"): object,
    vol.Optional("form"): dict,
})
@websocket_api.async_response
async def ws_request(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Passes a request from the Matkoll panel to the app, as the signed-in Home Assistant user."""
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_error(msg["id"], "not_loaded", "Matkoll isn't running")
        return
    try:
        result = await data["runner"].request(
            _ha_user(connection.user), msg["method"], msg["path"], msg.get("body"), msg.get("form"))
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Matkoll request %s %s failed", msg["method"], msg["path"])
        connection.send_error(msg["id"], "failed", str(err))
        return
    connection.send_result(msg["id"], result)
    if msg["method"] != "GET":
        await data["coordinator"].async_request_refresh()


async def _user_for_call(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Whose diary: the person given in the action, otherwise whoever triggered it."""
    user_id = None
    if person := call.data.get("person"):
        state = hass.states.get(person)
        user_id = state.attributes.get("user_id") if state else None
        if not user_id:
            raise HomeAssistantError(f"{person} isn't linked to a Home Assistant user")
    user_id = user_id or call.context.user_id
    if not user_id:
        raise HomeAssistantError("Choose a person: this action ran without a signed-in user (e.g. from an automation)")
    user = await hass.auth.async_get_user(user_id)
    if not user:
        raise HomeAssistantError("Unknown Home Assistant user")
    return _ha_user(user)


@callback
def _register_services(hass: HomeAssistant) -> None:
    async def log_food(call: ServiceCall) -> ServiceResponse:
        runner: MatkollRunner = hass.data[DOMAIN]["runner"]
        ha_user = await _user_for_call(hass, call)
        day = call.data.get("date")

        def run():
            account = runner.call("ensure_ha_user", ha_user["id"], ha_user["name"], ha_user["admin"])
            return runner.call("log_food_for", account["id"], call.data["food"], call.data["grams"],
                               call.data.get("meal"), day.isoformat() if day else None)
        try:
            result = await hass.async_add_executor_job(run)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await hass.data[DOMAIN]["coordinator"].async_request_refresh()
        return result if call.return_response else None

    async def sync_mealie(call: ServiceCall) -> ServiceResponse:
        runner: MatkollRunner = hass.data[DOMAIN]["runner"]
        try:
            status = await hass.async_add_executor_job(
                lambda: runner.call("mealie_sync", *runner.call("_sync_window")))
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"Mealie sync failed: {err}") from err
        await hass.data[DOMAIN]["coordinator"].async_request_refresh()
        return status if call.return_response else None

    hass.services.async_register(DOMAIN, "log_food", log_food, schema=LOG_FOOD_SCHEMA,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "sync_mealie", sync_mealie, schema=vol.Schema({}),
                                 supports_response=SupportsResponse.OPTIONAL)
