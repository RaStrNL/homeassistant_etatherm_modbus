"""homeassistant.components.climate.etatherm_modbus.

Etatherm climate control. Etatherm is product of Etatherm.cz, all trademarks apply.
"""

import asyncio
from datetime import timedelta
import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_PORT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import CONF_MODBUS_ADDR, HVACPreset_AUTO
from .etathermmodbus import EtathermModbus

_LOGGER = logging.getLogger(__name__)

VERSION = "1.1.1"

SUPPORT_FLAGS = 0


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Required(CONF_MODBUS_ADDR): cv.Number,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Sets up a Etatherm integration."""

    host = config.get(CONF_HOST, None)
    port = config.get(CONF_PORT, 50001)
    modbus_id = config.get(CONF_MODBUS_ADDR, 0)

    thermostats = []

    Etherm = EtathermModbus(host, port, modbus_id)

    Params = await Etherm.get_parameters()
    coordinator = EtathermCoordinator(hass, Etherm)
    _LOGGER.debug(Params)

    for idx, name in Params.items():
        _LOGGER.info("Thermostat Name: %s " % name)
        thermostats.append(EtathermThermostat(coordinator, idx, name, f"{host}-{idx}"))

    async_add_entities(thermostats, True)


class EtathermCoordinator(DataUpdateCoordinator):
    """Etatherm coordinator."""

    def __init__(self, hass: HomeAssistant, etherm: EtathermModbus) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Etatherm",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=15),
        )
        self.etherm = etherm

    async def setTemperature(self, pos, temperature) -> None:
        await self.etherm.set_temporary_temperature(pos, temperature, 120)

    async def setHVACMode(self, pos, hvac_mode) -> None:
        await self.etherm.set_mode(pos, hvac_mode == HVACMode.AUTO)

    async def __async_get_data(self) -> dict:
        async with asyncio.timeout(10):
            # Grab active context variables to limit data required to be fetched from API
            # Note: using context is not required if there is no need or ability to limit
            # data retrieved from API.
            listening_idx = set(self.async_contexts())
            current = await self.etherm.get_current_temperatures()
            required = await self.etherm.get_required_temperatures()
            data = {
                iid: {"curr": curr, "req": required[iid]}
                for iid, curr in current.items()
            }
            return data
        # except ApiAuthError as err:
        #     # Raising ConfigEntryAuthFailed will cancel future updates
        #     # and start a config flow with SOURCE_REAUTH (async_step_reauth)
        #     raise ConfigEntryAuthFailed from err
        # except ApiError as err:
        #     raise UpdateFailed(f"Error communicating with API: {err}")

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        # try:
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        return await self.__async_get_data()


class EtathermThermostat(CoordinatorEntity, ClimateEntity):
    """Representation of termostat."""

    coordinator: EtathermCoordinator

    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        #   | ClimateEntityFeature.PRESET_MODE
    )
    # _attr_preset_modes = [HVACPreset_AUTO, HVACPreset_KEEP]

    def __init__(self, coordinator: EtathermCoordinator, idx, params, uid) -> None:
        super().__init__(coordinator, context=idx)
        self._id = idx
        self._attr_unique_id = uid
        self._name = params["name"]
        self._attr_name = params["name"]
        self._current_temperature = None
        self._target_temperature = None
        self._attr_hvac_mode = HVACMode.AUTO
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        # self._attr_max_temp=
        # self._attr_min_temp=params['min']
        self._attr_preset_mode = HVACPreset_AUTO
        self._attr_target_temperature_high = params["max"]
        self._attr_target_temperature_low = params["min"]

    @property
    def name(self) -> str:
        """Return the name of the thermostat."""
        return self._name

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new mode."""
        if hvac_mode not in self._attr_hvac_modes:
            return
        await self.coordinator.setHVACMode(self._id, hvac_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._target_temperature = int(temperature)
        await self.coordinator.setTemperature(self._id, temperature)
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.coordinator.setHVACMode(self._id, hvac_mode)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is not None:
            self._current_temperature = self.coordinator.data[self._id]["curr"]
            self._target_temperature = self.coordinator.data[self._id]["req"]["temp"]
            if self._current_temperature < self._target_temperature:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.IDLE
            flag = self.coordinator.data[self._id]["req"]["flag"]
            match flag:
                case 0:
                    self._attr_hvac_mode = HVACMode.OFF
                case 1 | 4:
                    self._attr_hvac_mode = HVACMode.AUTO
                case 2 | 3:
                    self._attr_hvac_mode = HVACMode.HEAT
            self.async_write_ha_state()
