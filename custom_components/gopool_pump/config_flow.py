"""Config flow for GoPool Variable Speed Pump.

Two paths to get device_id + local_key + ip:
  - "manual": paste them directly (exactly like the localtuya template setup
    this integration replaces) — zero external dependency, always available.
  - "cloud_qr": scan a QR code with the Smart Life / Tuya Smart app (same
    mechanism Home Assistant's own official Tuya integration uses for its
    QR login step, reusing HA's public client_id/schema — see const.py for
    the sourcing/caveat notes). Used ONLY during setup to fetch credentials;
    nothing here keeps talking to the cloud afterward.
"""

from __future__ import annotations

import logging
from typing import Any

import tinytuya
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_USER_CODE,
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    TUYA_CLIENT_ID,
    TUYA_RESPONSE_CODE,
    TUYA_RESPONSE_MSG,
    TUYA_RESPONSE_QR_CODE,
    TUYA_RESPONSE_RESULT,
    TUYA_RESPONSE_SUCCESS,
    TUYA_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ["3.1", "3.2", "3.3", "3.4", "3.5"]


def _test_connection_sync(ip: str, device_id: str, local_key: str, protocol: str) -> bool:
    """Blocking connection test — must be called via async_add_executor_job.

    Never lets an exception escape: tinytuya can raise (socket timeout,
    connection refused, decrypt error, ...) instead of returning a clean
    failure dict, and an uncaught exception here surfaces to the user as
    the generic "Unknown error occurred" instead of a proper form error.
    """
    try:
        # This pump's device_id is 22 characters — tinytuya's own docs flag
        # that as needing dev_type='device22' explicitly when auto-detection
        # doesn't catch it, which matches what we observed (correct
        # device_id/local_key/IP still failing to poll).
        device = tinytuya.OutletDevice(
            dev_id=device_id, address=ip, local_key=local_key, dev_type="device22"
        )
        device.set_version(float(protocol))
        device.set_socketTimeout(5)
        result = device.status()
        # TEMP DEBUG — remove once the real failure cause is confirmed.
        _LOGGER.warning("GoPool debug: status() for %s returned: %s", ip, result)
        return bool(result and "dps" in result and not result.get("Error"))
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Local connection test to %s failed", ip)
        return False


class GoPoolPumpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoPool Variable Speed Pump."""

    VERSION = 1

    def __init__(self) -> None:
        self.__login_control = None
        self.__user_code: str = ""
        self.__qr_code: str = ""
        self.__manager = None
        self.__devices: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["manual", "cloud_qr"],
        )

    # ------------------------------------------------------------------
    # Path 1 — manual entry (no cloud dependency at all)
    # ------------------------------------------------------------------
    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            ok = await self.hass.async_add_executor_job(
                _test_connection_sync,
                user_input["ip"],
                user_input[CONF_DEVICE_ID],
                user_input[CONF_LOCAL_KEY],
                user_input[CONF_PROTOCOL_VERSION],
            )
            if ok:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get("name", "GoPool Pump"),
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default="GoPool Pump"): str,
                    vol.Required("ip"): str,
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_LOCAL_KEY): str,
                    vol.Required(
                        CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL_VERSION
                    ): vol.In(PROTOCOL_VERSIONS),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Path 2 — QR login, step A: ask for the Smart Life / Tuya Smart
    # "user code" (Profile -> Settings -> Account and Security -> user code
    # in the app — NOT the account email/password).
    # ------------------------------------------------------------------
    async def async_step_cloud_qr(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        from tuya_sharing import LoginControl

        if self.__login_control is None:
            self.__login_control = LoginControl()

        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            success, response = await self.__async_get_qr_code(user_input[CONF_USER_CODE])
            if success:
                return await self.async_step_scan()
            errors["base"] = "login_error"
            placeholders = {
                TUYA_RESPONSE_MSG: str(response.get(TUYA_RESPONSE_MSG, "Unknown error")),
                TUYA_RESPONSE_CODE: str(response.get(TUYA_RESPONSE_CODE, "0")),
            }

        return self.async_show_form(
            step_id="cloud_qr",
            data_schema=vol.Schema({vol.Required(CONF_USER_CODE): str}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def __async_get_qr_code(self, user_code: str) -> tuple[bool, dict[str, Any]]:
        response = await self.hass.async_add_executor_job(
            self.__login_control.qr_code, TUYA_CLIENT_ID, TUYA_SCHEMA, user_code
        )
        success = response.get(TUYA_RESPONSE_SUCCESS, False)
        if success:
            self.__user_code = user_code
            self.__qr_code = response[TUYA_RESPONSE_RESULT][TUYA_RESPONSE_QR_CODE]
        return success, response

    # ------------------------------------------------------------------
    # Path 2, step B: show the QR code, wait for it to be scanned.
    # ------------------------------------------------------------------
    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        qr_schema = vol.Schema(
            {
                vol.Optional("QR"): selector.QrCodeSelector(
                    config=selector.QrCodeSelectorConfig(
                        data=f"tuyaSmart--qrLogin?token={self.__qr_code}",
                        scale=5,
                        error_correction_level=selector.QrErrorCorrectionLevel.QUARTILE,
                    )
                )
            }
        )

        if user_input is None:
            return self.async_show_form(step_id="scan", data_schema=qr_schema)

        ret, info = await self.hass.async_add_executor_job(
            self.__login_control.login_result,
            self.__qr_code,
            TUYA_CLIENT_ID,
            self.__user_code,
        )
        if not ret:
            # QR token likely expired — request a fresh one and let the
            # user rescan.
            await self.__async_get_qr_code(self.__user_code)
            return self.async_show_form(
                step_id="scan",
                errors={"base": "login_error"},
                data_schema=qr_schema,
                description_placeholders={
                    TUYA_RESPONSE_MSG: str(info.get(TUYA_RESPONSE_MSG, "Unknown error")),
                    TUYA_RESPONSE_CODE: str(info.get(TUYA_RESPONSE_CODE, 0)),
                },
            )

        self.__token_info = {
            "t": info["t"],
            "uid": info["uid"],
            "expire_time": info["expire_time"],
            "access_token": info["access_token"],
            "refresh_token": info["refresh_token"],
        }
        self.__terminal_id = info["terminal_id"]
        self.__endpoint = info["endpoint"]

        return await self.async_step_pick_device()

    # ------------------------------------------------------------------
    # Path 2, step C: query the linked account's devices, let the user
    # pick which one is the pool pump, extract device_id + local_key.
    # ------------------------------------------------------------------
    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        from tuya_sharing import Manager, SharingTokenListener

        errors: dict[str, str] = {}

        if not self.__devices:
            class _NoopTokenListener(SharingTokenListener):
                def update_token(self, new_token_info: dict[str, Any]) -> None:
                    pass  # one-shot flow — nothing persists this session

            def _build_manager_and_list():
                manager = Manager(
                    TUYA_CLIENT_ID,
                    self.__user_code,
                    self.__terminal_id,
                    self.__endpoint,
                    self.__token_info,
                    _NoopTokenListener(),
                )
                manager.update_device_cache()
                return manager.device_map

            try:
                device_map = await self.hass.async_add_executor_job(_build_manager_and_list)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Failed to list Tuya devices after QR login")
                return self.async_abort(reason="device_list_failed")

            for dev_id, device in device_map.items():
                local_key = getattr(device, "local_key", None)
                if not local_key:
                    continue  # devices without a usable local_key are skipped
                # TEMP DEBUG — remove once local_key mismatch is diagnosed.
                _LOGGER.warning(
                    "GoPool debug: device_id=%s local_key=%s ip=%s (from Tuya cloud)",
                    dev_id,
                    local_key,
                    getattr(device, "ip", "") or "(none reported)",
                )
                self.__devices[dev_id] = {
                    "name": getattr(device, "name", dev_id),
                    "local_key": local_key,
                    "ip": getattr(device, "ip", "") or "",
                }

            if not self.__devices:
                return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            dev_id = user_input["device"]
            device = self.__devices[dev_id]
            ip = user_input.get("ip_override") or device["ip"]
            protocol = user_input[CONF_PROTOCOL_VERSION]

            if not ip:
                errors["ip_override"] = "ip_required"
            else:
                ok = await self.hass.async_add_executor_job(
                    _test_connection_sync, ip, dev_id, device["local_key"], protocol
                )
                if ok:
                    await self.async_set_unique_id(dev_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=device["name"],
                        data={
                            "name": device["name"],
                            "ip": ip,
                            CONF_DEVICE_ID: dev_id,
                            CONF_LOCAL_KEY: device["local_key"],
                            CONF_PROTOCOL_VERSION: protocol,
                        },
                    )
                errors["base"] = "cannot_connect"

        device_choices = {
            dev_id: f"{info['name']} ({dev_id})" for dev_id, info in self.__devices.items()
        }

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(device_choices),
                    vol.Optional("ip_override"): str,
                    vol.Required(
                        CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL_VERSION
                    ): vol.In(PROTOCOL_VERSIONS),
                }
            ),
            errors=errors,
        )
