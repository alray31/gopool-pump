"""Config flow for GoPool Variable Speed Pump.

Setup is QR-only: scan a code with the Smart Life / Tuya Smart app (same
mechanism Home Assistant's own official Tuya integration uses for its QR
login step, reusing HA's public client_id/schema — see const.py for the
sourcing/caveat notes) to fetch device_id + local_key, then confirm the
pump's local IP. Nothing here keeps talking to the cloud afterward — once
the config entry exists, the integration is 100% local.

The "scan" step auto-advances once the QR is scanned and confirmed on the
phone — no manual Submit click needed. This uses HA's async_show_progress /
async_show_progress_done mechanism (the same pattern HA's own built-in
GitHub integration uses for its device-code login step): a background task
polls tuya_sharing's login_result() every TUYA_QR_POLL_INTERVAL seconds,
and the frontend re-invokes async_step_scan on its own until that task
finishes — see __wait_for_scan() below for the polling/QR-refresh logic,
and _qr_code_html()'s docstring for why the QR is rendered via HA's own
<ha-qr-code> element instead of the QrCodeSelector form field this step
used to have (progress steps don't support form fields at all).

Protocol version is fixed at 3.5 (this pump line only ships that version;
see DEFAULT_PROTOCOL_VERSION in const.py) — not exposed as a choice.

Reauth (async_step_reauth): triggered automatically by Home Assistant
when GoPoolCoordinator raises ConfigEntryAuthFailed (__init__.py) after
tinytuya reports the stored local_key was rejected — most commonly
because the pump was removed and re-added in the Smart Life app, which
rotates its local_key. Reruns the exact same
user -> scan -> pick_device steps as a fresh setup (nothing shortened:
a new local_key can only be fetched via a fresh cloud login), except
async_step_pick_device pre-selects the already-configured device_id
when the account still reports it, and updates the existing config
entry in place instead of creating a new one — see the
`self.source == SOURCE_REAUTH` branches there.

Reconfigure (async_step_reconfigure): the user-triggered counterpart for
when it's the pump's LAN IP that changed instead of its local_key — no
cloud login needed, just a new address to test against the credentials
already stored. See that method's own docstring for why this one isn't
auto-triggered the way reauth is, and GoPoolCoordinator's _maybe_heal_ip
(__init__.py) for the background self-healing attempt that runs before
a user would ever need this.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

import tinytuya
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from . import pump_model_label
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
    QR_SCAN_GIF_URL,
    TUYA_CLIENT_ID,
    TUYA_QR_MAX_CONSECUTIVE_ERRORS,
    TUYA_QR_POLL_INTERVAL,
    TUYA_QR_REFRESH_AFTER,
    TUYA_RESPONSE_CODE,
    TUYA_RESPONSE_MSG,
    TUYA_RESPONSE_QR_CODE,
    TUYA_RESPONSE_RESULT,
    TUYA_RESPONSE_SUCCESS,
    TUYA_SCHEMA,
    USER_CODE_GIF_URL,
)
from .discovery import scan_for_lan_ips
from .logic import pick_reauth_default_device

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


def _pump_model_selector(hass: HomeAssistant) -> selector.SelectSelector:
    """Radio-button selector for PUMP_MODELS (used both at initial setup and
    in the options flow), with plain-language option labels (e.g. "AG1
    (Above-ground pool, 1.5 HP)") instead of the bare model code. A plain
    vol.In(PUMP_MODELS) would only ever show the raw codes.

    Labels are literal strings built via pump_model_label() (same helper
    the device info card uses — see __init__.py), NOT a translation_key
    selector: HA's SelectSelector translation-key mechanism requires every
    OPTION VALUE to itself be a valid translation key ([a-z0-9-_]+, no
    uppercase), and PUMP_MODELS' real values ("AG1", "IG1", "IG2") fail
    that — hassfest rejects a "selector.pump_model.options.AG1" key outright.
    Literal SelectOptionDict labels sidestep the constraint entirely; the
    trade-off is that the label text follows the HA server's configured
    language (hass.config.language) rather than each viewer's own browser
    language, same as the device card.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=model, label=pump_model_label(hass, model))
                for model in PUMP_MODELS
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _qr_code_html(token: str) -> str:
    """Render the Smart Life / Tuya Smart QR login payload as HA's own
    <ha-qr-code> element, embedded directly in markdown-rendered step
    description text via a "{qr_code}" placeholder (same mechanism
    already used for the GIF URLs in this file).

    This started out as a hand-generated inline <svg>, which turned out
    to render as a tiny, black-background, unreadable mess: HA's markdown
    sanitizer (custom_components use the "xss" package, not DOMPurify —
    see src/resources/markdown-worker.ts) whitelists only "xmlns",
    "height" and "width" on a raw <svg> tag and only "transform",
    "stroke", "d" on <path> — NOT "viewBox" and NOT "fill", and <rect>
    isn't whitelisted at all. Without viewBox the QR's module-grid
    coordinates never get rescaled to the requested width/height (hence
    "tiny"), and with no <rect> allowed there's no way to paint a light
    background behind the (default-black, since "fill" is stripped too)
    modules (hence "black background").

    <ha-qr-code>, however, is in that sanitizer's BASE allowlist
    (unconditionally, unlike raw <svg> which needs allow-svg) — it's a
    real HA frontend component (renders to a <canvas> via the "qrcode" JS
    package, same project as the "qrcode" PyPI package this used to
    depend on), so it needs no dependency here anymore and isn't subject
    to the markdown sanitizer's SVG attribute stripping at all. It also
    automatically resolves a theme-contrast-safe foreground/background
    from HA's own CSS variables, so it matches light/dark theme instead
    of assuming a fixed white background.

    "width" here is the total rendered size in CSS pixels (forces the
    per-module scale to fit, per the underlying "qrcode" package's
    toCanvas() option) — NOT a module count, unlike the "width" this
    project's DP config uses elsewhere for unrelated things.
    """
    return (
        f'<ha-qr-code data="{html.escape(f"tuyaSmart--qrLogin?token={token}")}" '
        'error-correction-level="quartile" width="260"></ha-qr-code>'
    )


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
        # dev_id -> LAN IP, from a local UDP scan (see scan_for_lan_ips() in discovery.py)
        # — populated once, right after __devices, best-effort.
        self.__discovered_ips: dict[str, str] = {}
        # Background poller for the "scan" step (see __wait_for_scan()) and
        # the QR it's currently displaying, kept as instance state so a
        # silent QR refresh mid-poll is picked up the next time
        # async_step_scan re-renders the progress screen.
        self.__scan_task: asyncio.Task[None] | None = None
        self.__qr_code_html: str = ""
        # Set only by async_step_reauth — the device_id already configured
        # on the entry being reauthenticated, used by async_step_pick_device
        # to pre-select the same device instead of asking the user to pick
        # it again (see pick_reauth_default_device() in logic.py).
        self._reauth_device_id: str | None = None

    # ------------------------------------------------------------------
    # Reauth entry point — see the module docstring's "Reauth" section.
    # Home Assistant calls this (not async_step_user) when it starts a
    # reauth flow; `entry_data` is the failing entry's current .data.
    # ------------------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_device_id = entry_data.get(CONF_DEVICE_ID)
        return await self.async_step_user()

    # ------------------------------------------------------------------
    # Entry point — ask for the Smart Life / Tuya Smart "user code"
    # (Profile -> Settings -> Account and Security -> user code in the
    # app — NOT the account email/password).
    #
    # Also the step Home Assistant lands on for reauth (via
    # async_step_reauth above): re-entering the user code is genuinely
    # required there too, not just for a fresh setup — fetching a new
    # local_key means logging into the Smart Life cloud again, the same
    # as initial setup. The form/description shown is identical either
    # way; Home Assistant's own dialog chrome already distinguishes a
    # reauth flow ("Reauthenticate ...") from a fresh one ("Set up ...")
    # without this step needing separate translation strings for both.
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        from tuya_sharing import LoginControl

        if self.__login_control is None:
            self.__login_control = LoginControl()

        errors: dict[str, str] = {}
        # Always present: hassfest's translation linter forbids a literal
        # URL inside a translation string, so the GIF's URL is referenced
        # in strings.json/translations/*.json as "{user_code_gif_url}" and
        # supplied here instead — needed on every render of this step, not
        # just the error path.
        placeholders: dict[str, str] = {"user_code_gif_url": USER_CODE_GIF_URL}

        if user_input is not None:
            success, response = await self.__async_get_qr_code(user_input[CONF_USER_CODE])
            if success:
                return await self.async_step_scan()
            errors["base"] = "login_error"
            placeholders[TUYA_RESPONSE_MSG] = str(response.get(TUYA_RESPONSE_MSG, "Unknown error"))
            placeholders[TUYA_RESPONSE_CODE] = str(response.get(TUYA_RESPONSE_CODE, "0"))

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
    # Show the QR code and wait for it to be scanned — auto-advances on
    # its own once confirmed, no Submit click required. See the module
    # docstring and _qr_code_html()/__wait_for_scan() for how/why.
    # ------------------------------------------------------------------
    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.__scan_task is None:
            self.__qr_code_html = _qr_code_html(self.__qr_code)
            self.__scan_task = self.hass.async_create_task(
                self.__wait_for_scan(), f"{DOMAIN}_qr_scan"
            )

        if not self.__scan_task.done():
            # Same reasoning as async_step_user for the GIF placeholder:
            # hassfest rejects a literal URL in a translation string. The
            # QR itself is embedded the same way — see _qr_code_html().
            return self.async_show_progress(
                step_id="scan",
                progress_action="waiting_for_scan",
                progress_task=self.__scan_task,
                description_placeholders={
                    "qr_scan_gif_url": QR_SCAN_GIF_URL,
                    "qr_code": self.__qr_code_html,
                },
            )

        try:
            self.__scan_task.result()
        except Exception:  # noqa: BLE001
            # TUYA_QR_MAX_CONSECUTIVE_ERRORS consecutive transport
            # failures — a real connectivity/API problem, not a plain
            # "not scanned yet" response (see __wait_for_scan()).
            _LOGGER.exception("QR login never completed")
            return self.async_show_progress_done(next_step_id="scan_failed")

        return self.async_show_progress_done(next_step_id="pick_device")

    async def async_step_scan_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reached only after repeated transport failures while polling
        login_result() — see async_step_scan / __wait_for_scan."""
        return self.async_abort(reason="qr_login_failed")

    async def __wait_for_scan(self) -> None:
        """Background task backing the "scan" progress step.

        Polls login_result() every TUYA_QR_POLL_INTERVAL seconds instead
        of waiting for a manual Submit click — HA's frontend re-invokes
        async_step_scan on its own while this task is running (that's
        what async_show_progress/progress_task is for) and again once it
        finishes.

        Tuya doesn't document a fixed QR-token lifetime, so rather than
        ever surfacing a hard "expired" error to the user, a fresh QR is
        silently requested every TUYA_QR_REFRESH_AFTER seconds of no
        confirmation — self.__qr_code_html is updated in place and picked
        up on the next progress render automatically.

        Returns normally once the login is confirmed. Re-raises after
        TUYA_QR_MAX_CONSECUTIVE_ERRORS consecutive *transport* failures
        (a "not scanned yet" response from Tuya is expected/normal and
        does not count as an error here).
        """
        consecutive_errors = 0
        since_refresh = 0
        while True:
            await asyncio.sleep(TUYA_QR_POLL_INTERVAL)
            since_refresh += TUYA_QR_POLL_INTERVAL
            try:
                ret, info = await self.hass.async_add_executor_job(
                    self.__login_control.login_result,
                    self.__qr_code,
                    TUYA_CLIENT_ID,
                    self.__user_code,
                )
            except Exception:  # noqa: BLE001
                consecutive_errors += 1
                _LOGGER.debug("QR login status check failed", exc_info=True)
                if consecutive_errors >= TUYA_QR_MAX_CONSECUTIVE_ERRORS:
                    raise
                continue

            consecutive_errors = 0

            if ret:
                self.__token_info = {
                    "t": info["t"],
                    "uid": info["uid"],
                    "expire_time": info["expire_time"],
                    "access_token": info["access_token"],
                    "refresh_token": info["refresh_token"],
                }
                self.__terminal_id = info["terminal_id"]
                self.__endpoint = info["endpoint"]
                return

            if since_refresh >= TUYA_QR_REFRESH_AFTER:
                since_refresh = 0
                success, _resp = await self.__async_get_qr_code(self.__user_code)
                if success:
                    self.__qr_code_html = _qr_code_html(self.__qr_code)
                # A failed refresh just leaves the previous (possibly
                # stale) code in place — not fatal, the next successful
                # refresh replaces it; the user isn't shown anything.

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

            # Best-effort: try to find each device's real LAN IP via a
            # local UDP scan before showing the form, so "ip" below can be
            # pre-filled with something more trustworthy than the cloud's
            # often-public-facing address — see scan_for_lan_ips() in discovery.py.
            self.__discovered_ips = await self.hass.async_add_executor_job(
                scan_for_lan_ips, list(self.__devices)
            )

        # Reauth (see async_step_reauth / the module docstring's "Reauth"
        # section): update the existing entry in place instead of creating
        # a new one. `reauth_entry` is None for a fresh setup.
        is_reauth = self.source == SOURCE_REAUTH
        reauth_entry = self._get_reauth_entry() if is_reauth else None

        if user_input is not None:
            dev_id = user_input["device"]
            device = self.__devices[dev_id]
            ip = user_input["ip"]
            pump_model = user_input[CONF_PUMP_MODEL]

            ok = await self.hass.async_add_executor_job(
                _test_connection_sync, ip, dev_id, device["local_key"]
            )
            if ok:
                new_data = {
                    "name": device["name"],
                    "ip": ip,
                    CONF_DEVICE_ID: dev_id,
                    CONF_LOCAL_KEY: device["local_key"],
                    CONF_PROTOCOL_VERSION: DEFAULT_PROTOCOL_VERSION,
                    CONF_PUMP_MODEL: pump_model,
                }
                if reauth_entry is not None:
                    if dev_id != reauth_entry.unique_id:
                        # Edge case: the account no longer has the
                        # originally-configured device_id (see
                        # pick_reauth_default_device()'s docstring in
                        # logic.py) and the user picked a different device
                        # from the full list instead — guard against
                        # silently "adopting" one that's already the
                        # unique_id of some OTHER config entry.
                        await self.async_set_unique_id(dev_id)
                        self._abort_if_unique_id_configured()
                    return self.async_update_reload_and_abort(
                        reauth_entry, data_updates=new_data
                    )
                await self.async_set_unique_id(dev_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=device["name"], data=new_data)
            errors["base"] = "cannot_connect"

        device_choices = {
            dev_id: f"{info['name']} ({dev_id})" for dev_id, info in self.__devices.items()
        }
        # Which device the selector defaults to: reauth prefers the
        # device_id already on the entry being reauthenticated (when the
        # account still reports it) — see pick_reauth_default_device() in
        # logic.py. A fresh setup gets that same function's plain
        # "first device" fallback, unchanged from before reauth existed
        # (HA's frontend used to supply this implicitly when "device" had
        # no explicit default at all; now it's explicit either way).
        default_device = pick_reauth_default_device(self.__devices, self._reauth_device_id)
        # Pre-fill "ip":
        # - Reauth: the entry's last-known IP first — the pump usually
        #   kept the same LAN IP (a static IP is recommended in the
        #   README precisely so this holds), and re-testing it is exactly
        #   what happens on Submit below regardless.
        # - Preferred fallback either way: the LAN IP a local UDP scan
        #   actually found for this device_id (see scan_for_lan_ips() in discovery.py —
        #   call already made above).
        # - Last resort: the cloud-reported IP, but ONLY when it looks
        #   like a private LAN address — Tuya's device-sharing API
        #   frequently reports a public/WAN address instead, never
        #   trusted as-is.
        discovered_ip = self.__discovered_ips.get(default_device, "") if default_device else ""
        if discovered_ip:
            scanned_default_ip = discovered_ip
        else:
            first_ip = self.__devices.get(default_device, {}).get("ip", "")
            scanned_default_ip = first_ip if _looks_private(first_ip) else ""
        default_ip = (
            reauth_entry.data.get("ip") or scanned_default_ip
            if reauth_entry is not None
            else scanned_default_ip
        )
        default_pump_model = (
            reauth_entry.options.get(
                CONF_PUMP_MODEL, reauth_entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL)
            )
            if reauth_entry is not None
            else DEFAULT_PUMP_MODEL
        )

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device", default=default_device): vol.In(device_choices),
                    vol.Required("ip", default=default_ip): str,
                    vol.Required(
                        CONF_PUMP_MODEL, default=default_pump_model
                    ): _pump_model_selector(self.hass),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Manual "Reconfigure" entry point (Settings -> Devices & services ->
    # this integration -> "..." -> Reconfigure) for when the pump's LAN IP
    # changed and it's no longer reachable at the address on the entry.
    #
    # Deliberately NOT the same user -> scan -> pick_device journey as
    # async_step_reauth: the local_key hasn't changed here, only the IP,
    # so there's nothing to re-fetch from the Smart Life cloud — this is
    # a single short step that re-tests the EXISTING credentials against
    # a new address, pre-filled via the same passive LAN scan setup uses
    # (see discovery.py) when it can find the pump.
    #
    # Home Assistant does not trigger this one automatically the way it
    # does async_step_reauth for ConfigEntryAuthFailed — a plain
    # connectivity failure isn't necessarily permanent, so there's no
    # built-in "start a reconfigure flow" signal to hook into. Between
    # this and GoPoolCoordinator's own background self-healing attempt
    # (see _maybe_heal_ip in __init__.py, which tries the same scan
    # automatically after sustained failures), this manual step is the
    # fallback for when that best-effort scan can't see the pump either
    # (e.g. HA can't observe LAN broadcast traffic at all — see
    # discovery.py's docstring) and the user has to type the IP in
    # themselves.
    # ------------------------------------------------------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        discovered_ip = ""
        if user_input is None:
            found = await self.hass.async_add_executor_job(
                scan_for_lan_ips, [entry.data[CONF_DEVICE_ID]]
            )
            discovered_ip = found.get(entry.data[CONF_DEVICE_ID], "")

        if user_input is not None:
            ip = user_input["ip"]
            ok = await self.hass.async_add_executor_job(
                _test_connection_sync, ip, entry.data[CONF_DEVICE_ID], entry.data[CONF_LOCAL_KEY]
            )
            if ok:
                return self.async_update_reload_and_abort(entry, data_updates={"ip": ip})
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required("ip", default=discovered_ip or entry.data.get("ip", "")): str}
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
                {vol.Required(CONF_PUMP_MODEL, default=current): _pump_model_selector(self.hass)}
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
