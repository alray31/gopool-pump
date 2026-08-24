"""Config flow for GoPool Variable Speed Pump.

Setup is QR-only: scan a code with the Smart Life / Tuya Smart app (same
mechanism Home Assistant's own official Tuya integration uses for its QR
login step, reusing HA's public client_id/schema — see const.py for the
sourcing/caveat notes) to fetch device_id + local_key, then confirm the
pump's local IP. Nothing here keeps talking to the cloud afterward — once
the config entry exists, the integration is 100% local.

Protocol version is fixed at 3.5 (this pump line only ships that version;
see DEFAULT_PROTOCOL_VERSION in const.py) — not exposed as a choice.
"""

from __future__ import annotations

import logging
from typing import Any

import tinytuya
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_PUMP_MODEL,
    CONF_USER_CODE,
    DEFAULT_PROTOCOL_VERSION,
    DEFAULT_PUMP_MODEL,
    DOMAIN,
    PUMP_MODELS,
    TUYA_CLIENT_ID,
    TUYA_RESPONSE_CODE,
    TUYA_RESPONSE_MSG,
    TUYA_RESPONSE_QR_CODE,
    TUYA_RESPONSE_RESULT,
    TUYA_RESPONSE_SUCCESS,
    TUYA_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)


def _test_connection_sync(ip: str, device_id: str, local_key: str) -> bool:
    """Blocking connection test — must be called via async_add_executor_job.

    Never lets an exception escape: tinytuya can raise (socket timeout,
    connection refused, decrypt error, ...) instead of returning a clean
    failure dict, and an uncaught exception here surfaces to the user as
    the generic "Unknown error occurred" instead of a proper form error.
    """
    try:
        device = tinytuya.OutletDevice(dev_id=device_id, address=ip, local_key=local_key)
        device.set_version(float(DEFAULT_PROTOCOL_VERSION))
        # 8s: generous margin over the ~0.06s TCP connect measured on a real
        # pump — kept short so a genuinely unreachable IP fails fast during
        # setup instead of leaving the user staring at a spinner.
        device.set_socketTimeout(8)
        result = device.status()
        return bool(result and "dps" in result and not result.get("Error"))
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Local connection test to %s failed", ip)
        return False


class GoPoolPumpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoPool Variable Speed Pump."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GoPoolPumpOptionsFlow()

    def __init__(self) -> None:
        self.__login_control = None
        self.__user_code: str = ""
        self.__qr_code: str = ""
        self.__token_info: dict[str, Any] = {}
        self.__terminal_id: str = ""
        self.__endpoint: str = ""
        self.__devices: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Entry point — ask for the Smart Life / Tuya Smart "user code"
    # (Profile -> Settings -> Account and Security -> user code in the
    # app — NOT the account email/password).
    # ------------------------------------------------------------------
    async def async_step_user(
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
            step_id="user",
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
    # Show the QR code, wait for it to be scanned.
    # ------------------------------------------------------------------
    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        from homeassistant.helpers import selector

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
    # Query the linked account's devices, let the user pick which one is
    # the pool pump, extract device_id + local_key.
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
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to list Tuya devices after QR login")
                return self.async_abort(reason="device_list_failed")

            for dev_id, device in device_map.items():
                local_key = getattr(device, "local_key", None)
                if not local_key:
                    continue  # devices without a usable local_key are skipped
                self.__devices[dev_id] = {
                    "name": getattr(device, "name", dev_id),
                    "local_key": local_key,
                    # The cloud-reported IP is frequently a public/WAN
                    # address (Tuya's device-sharing API does not
                    # reliably report the LAN IP) — never trusted as a
                    # silent default, always confirmed/entered below.
                    "ip": getattr(device, "ip", "") or "",
                }

            if not self.__devices:
                return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            dev_id = user_input["device"]
            device = self.__devices[dev_id]
            ip = user_input["ip"]
            pump_model = user_input[CONF_PUMP_MODEL]

            ok = await self.hass.async_add_executor_job(
                _test_connection_sync, ip, dev_id, device["local_key"]
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
                        CONF_PROTOCOL_VERSION: DEFAULT_PROTOCOL_VERSION,
                        CONF_PUMP_MODEL: pump_model,
                    },
                )
            errors["base"] = "cannot_connect"

        device_choices = {
            dev_id: f"{info['name']} ({dev_id})" for dev_id, info in self.__devices.items()
        }
        # Pre-fill the IP field with the cloud-reported value only when it
        # looks like a private LAN address — never with a public IP.
        first_ip = next(iter(self.__devices.values()), {}).get("ip", "")
        default_ip = first_ip if _looks_private(first_ip) else ""

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): vol.In(device_choices),
                    vol.Required("ip", default=default_ip): str,
                    vol.Required(CONF_PUMP_MODEL, default=DEFAULT_PUMP_MODEL): vol.In(
                        PUMP_MODELS
                    ),
                }
            ),
            errors=errors,
        )


class GoPoolPumpOptionsFlow(OptionsFlow):
    """Lets the pump model — used only to pick the RPM->W calibration curve
    for the Power Draw / Energy sensors, see RPM_POWER_TABLES in const.py —
    be changed after initial setup, without deleting and re-adding the
    integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_PUMP_MODEL,
            self.config_entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_PUMP_MODEL, default=current): vol.In(PUMP_MODELS)}
            ),
        )


def _looks_private(ip: str) -> bool:
    """True for RFC1918 private ranges — a cheap guard against pre-filling
    a public/WAN IP the Tuya cloud API sometimes reports for shared
    devices."""
    if not ip:
        return False
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
