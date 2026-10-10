from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity, DeviceInfo, EntityCategory
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import slugify

from .const import DOMAIN, HUB_IDENTIFIER, SIGNAL_NEW_ENTITY, SIGNAL_REMOVE_ENTITY, SIGNAL_STATE_UPDATE


def async_setup_dynamic_platform(hass, entry, async_add_entities, domain_key, entity_cls, hub):
    added = set()

    @callback
    def _add(unique_id):
        if unique_id in added:
            return
        added.add(unique_id)
        async_add_entities([entity_cls(hub, unique_id)])

    @callback
    def _remove(unique_id):
        added.discard(unique_id)
        ent_reg = er.async_get(hass)
        entity_id = ent_reg.async_get_entity_id(domain_key, DOMAIN, unique_id)
        if entity_id:
            ent_reg.async_remove(entity_id)

    for uid, e in list(hub.entities.items()):
        if e.get("domain") == domain_key:
            _add(uid)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_ENTITY.format(domain=domain_key), _add)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_REMOVE_ENTITY.format(domain=domain_key), _remove)
    )


def compute_suggested_object_id(config, device_id, object_id):
    config = config or {}
    default_entity_id = config.get("default_entity_id")
    if default_entity_id and "." in default_entity_id:
        suffix = default_entity_id.split(".", 1)[1]
        device = config.get("device") or {}
        device_slug = slugify(device.get("name") or device_id or "")
        prefix = f"{device_slug}_"
        if device_slug and suffix.startswith(prefix):
            return suffix[len(prefix):]
        return suffix

    if object_id:
        return slugify(object_id)

    return None


_READ_ONLY_ENTITY_CLASSES = frozenset({"TuxdSensor", "TuxdBinarySensor", "TuxdUpdate"})


class TuxdEntity(Entity):

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, hub, unique_id):
        self.hub = hub
        self._unique_id = unique_id

    @property
    def _entry(self):
        return self.hub.entities.get(self._unique_id) or {}

    @property
    def _config(self):
        return self._entry.get("config") or {}

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def available(self):
        entry = self._entry
        if not entry:
            return False
        if type(self).__name__ == "TuxdButton":
            return entry.get("device_id") in self.hub.devices
        return True

    @property
    def name(self):
        return self._config.get("name")

    @property
    def icon(self):
        return self._config.get("icon")

    @property
    def suggested_object_id(self):
        return compute_suggested_object_id(
            self._config, self._entry.get("device_id"), self._entry.get("object_id")
        )

    @property
    def entity_category(self):
        try:
            category = EntityCategory(self._config.get("entity_category"))
        except ValueError:
            return None
        if category is EntityCategory.CONFIG and type(self).__name__ in _READ_ONLY_ENTITY_CLASSES:
            return EntityCategory.DIAGNOSTIC
        return category

    @property
    def device_info(self):
        dev = self._config.get("device") or {}
        identifiers = dev.get("identifiers") or [self._entry.get("device_id")]
        dev_reg = dr.async_get(self.hass)
        hub_device = dev_reg.async_get_device_by_identifier((DOMAIN, HUB_IDENTIFIER), self.hub.entry.entry_id)
        return DeviceInfo(
            identifiers={(DOMAIN, i) for i in identifiers if i},
            name=dev.get("name"),
            manufacturer=dev.get("manufacturer"),
            model=dev.get("model"),
            sw_version=dev.get("sw_version"),
            via_device_id=hub_device.id if hub_device else None,
        )

    @property
    def extra_state_attributes(self):
        attrs = self._entry.get("attributes")
        return attrs or None

    def _send_command(self, key, payload):
        device_id = self._entry.get("device_id")
        if not device_id:
            return
        if device_id not in self.hub.devices:
            raise HomeAssistantError(f"TuxD device {device_id} is offline")
        self.hub.send_command(device_id, key, payload)

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATE_UPDATE.format(unique_id=self._unique_id),
                self.async_write_ha_state,
            )
        )
