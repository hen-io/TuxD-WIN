import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN


class TuxdPendingDevicesRepairFlow(RepairsFlow):

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        hub = self.hass.data[DOMAIN][self.data["entry_id"]]

        if user_input is not None:
            issued = {}
            for device_id in user_input.get("approve") or []:
                new_key = await hub.approve_device(device_id)
                if new_key:
                    issued[device_id] = new_key
            for device_id in user_input.get("reject") or []:
                await hub.reject_device(device_id)
            if issued:
                return await self.async_step_issued(issued=issued)
            return self.async_create_entry(data={})

        pending = hub.pending_devices
        choices = {
            device_id: f"{device_id} (model: {info.get('model') or 'unknown'}, "
                       f"version: {info.get('sw_version') or 'unknown'})"
            for device_id, info in pending.items()
        }
        schema = vol.Schema({
            vol.Optional("approve", default=[]): cv.multi_select(choices),
            vol.Optional("reject", default=[]): cv.multi_select(choices),
        })
        return self.async_show_form(step_id="confirm", data_schema=schema)

    async def async_step_issued(self, user_input=None, issued=None):
        if issued is not None:
            self._issued = issued
        if user_input is not None:
            return self.async_create_entry(data={})
        lines = "\n".join(f"- **{d}**: `{k}`" for d, k in self._issued.items())
        return self.async_show_form(
            step_id="issued",
            data_schema=vol.Schema({}),
            description_placeholders={"keys": lines},
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict | None) -> RepairsFlow:
    return TuxdPendingDevicesRepairFlow()
