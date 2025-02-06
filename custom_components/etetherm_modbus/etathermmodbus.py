"""Etatherm lib using Modbus."""

from array import array
import asyncio
from datetime import datetime, timedelta
import logging
from math import floor

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.payload import BinaryPayloadBuilder, BinaryPayloadDecoder
from .const import CONF_MODBUS_RETR, CONF_MODBUS_RETR_WAIT, CONF_MODBUS_TIMEOUT
_LOGGER = logging.getLogger(__name__)


class EtathermModbus:
    """Access to Etatherm climate control by Modbus protocol."""
    def __init__(
        self,
        host,
        port,
        address,
    ):
        """Init method."""
        self._client = AsyncModbusTcpClient(host=host, port=port, timeout= CONF_MODBUS_TIMEOUT)
        self._address = address
        self._params = None
        self._lock = asyncio.Lock()
    async def get_parameters(self) -> dict[int, dict[str, str]] | None:
        """Read positions configuration parameters."""
        if self._params is None:
            await self.__read_params()
        if self._params is None:
            return None
        return {
            pos: {
                "name": p["name"],
                "min": (1 + p["shift"]) * p["step"],
                "max": (30 + p["shift"]) * p["step"],
            }
            for pos, p in self._params.items()
            if p["used"]
        }

    async def set_mode(self, pos: int, auto: bool) -> bool:
        """Set heating mode."""
        start = 0x1100
        addr = start + (pos - 1) * 0x10 + 0x03
        response = await self.async_read_holding_registers(self._address, addr, 6)
        if response.isError():
            return False
        data = bytes(response.registers)
        if auto:
            data = bytes([data[0] & 0xDF]) + b"\x10\x80\x10\x80"
        else:
            data = bytes([data[0] | 0x20]) + data[1:5]
        response = await self.async_write_register(self._address, addr, data)
        if response.isError():
            return False
        return True

    async def set_temporary_temperature(
        self, pos: int, temperature: int, duration: int = 120
    ) -> bool:
        """Set temporary temperature on position. :Operativní změna:"""
        start = 0x1100
        addr = start + (pos - 1) * 0x10 + 0x03

        if self._params is None:
            await self.__read_params()
        position = self._params[pos]
        temp = (floor(temperature) // position["step"] - position["shift"]) & 0x1F

        response = await self.async_read_holding_registers(self._address, addr, 1)
        if response.isError():
            return False
        data = bytes(response.registers)
        now = datetime.now()
        start = self.__get_toy(now - timedelta(minutes=0))
        end = self.__get_toy(now + timedelta(minutes=duration + 1))
        data = (
            bytes([(data[0] & 0xC0) + temp])
            + start.to_bytes(2, "big")
            + end.to_bytes(2, "big")
        )
        response = await self.async_write_register(self._address, addr, data)
        if response.isError():
            return False
        return True

    async def get_current_temperatures(self) -> dict[int, int] | None:
        """Read actual temperatures as measured on all positions."""
        response = await self.async_read_holding_registers(self._address, 0x60, 16)
        data = bytes(response.registers)
        if self._params is None:
            await self.__read_params()
        if data is None or len(data) != 16 or self._params is None:
            return None
        res = {}
        for pos in range(1, 17):
            b = data[pos - 1]
            position = self._params[pos]
            if position["used"]:
                res[pos] = (b + position["shift"]) * position["step"]
        return res

    async def get_required_temperatures(self) -> dict[int, dict[str, any]] | None:
        """Returns "temp" - required temperature, "flag" - 0:summer, 1:HDO, 2:temporary temperature, 3:permanent temperature, 4:scheduled"""
        response = await self.async_read_holding_registers(self._address, 0x70, 16)
        data = bytes(response.registers)
        if self._params is None:
            await self.__read_params()
        if data is None or len(data) != 16 or self._params is None:
            return None
        res = {}
        for pos in range(1, 17):
            b = data[pos - 1] & 0x1F
            flag = data[pos - 1] >> 5
            position = self._params[pos]
            if position["used"]:
                res[pos] = {
                    "temp": (b + position["shift"]) * position["step"],
                    "flag": flag,
                }
        return res

    def __get_toy(self, time_in: datetime) -> int:
        return (
            (time_in.minute // 15)
            + (time_in.hour * 4)
            + (time_in.day * 32 * 4)
            + (time_in.month * 32 * 32 * 4)
        )

    async def __read_params(self) -> None:
        start = 0x1100
        name_start = 0x1030
        res = {}
        for pos in range(1, 17):
            addr = start + (pos - 1) * 0x10
            param_response = await self.async_read_holding_registers(
                self._address, addr, 4
            )
            if param_response.isError():
                res[pos] = {"used": False, "name": "<timeout>", "shift": 5, "step": 1}
                continue
            params = bytes(param_response.registers)
            used = params[0] & 0x07
            used = used != 0
            shift = params[2] & 0x3F
            shift = shift - (64 * (shift // 32))
            step = (params[2] & 0xC0) >> 6
            step = step + 1
            if used:
                addr = name_start + (pos - 1) * 8
                name_response = await self.async_read_holding_registers(
                    self._address, addr, 8
                )
                if param_response.isError():
                    name = b""
                else:
                    name = bytes(name_response.registers)
                end = name.find(b"\x00")
                if end != -1:
                    name = name[:end]
                name = name.decode("1250")
            else:
                name = ""
            res[pos] = {"used": used, "name": name, "shift": shift, "step": step}
        self._params = res

    async def __async_close(self):
        """Disconnect client."""
        if self._client.connected:
            self._client.close()

    async def __check_connection(self):
        if not self._client.connected:
            _LOGGER.info("Etatherm is not connected, trying to connect.")
            return await self.__async_connect()
        return self._client.connected

    async def __async_connect(self):
        result = False

        _LOGGER.debug(
            "Trying to connect to Etatherm at %s:%s",
            self._client.comm_params.host,
            self._client.comm_params.port,
        )

        result = await self._client.connect()

        if result:
            _LOGGER.info(
                "Etatherm connected at %s:%s",
                self._client.comm_params.host,
                self._client.comm_params.port,
            )
        else:
            _LOGGER.warning(
                "Unable to connect to Etatherm at %s:%s",
                self._client.comm_params.host,
                self._client.comm_params.port,
            )
        return result

    async def async_read_holding_registers(self, unit, address, count):
        """Read holding registers."""
        kwargs = {"slave": unit} if unit else {}
        async with self._lock:
            await self.__check_connection()
            for i in range (0, CONF_MODBUS_RETR):
                regs_l = await self._client.read_holding_registers(address, count=count, **kwargs)
                if regs_l.isError():
                    await asyncio.sleep(CONF_MODBUS_RETR_WAIT)			
                else:
                    break
            return regs_l

    async def async_write_register(self, unit, address, payload: bytes):
        kwargs = {"slave": unit} if unit else {}

        async with self._lock:
            await self.__check_connection()
            for i in range (0, CONF_MODBUS_RETR):
                regs_l = await self._client.write_registers(address, list(payload), **kwargs)
                if regs_l.isError():
                    await asyncio.sleep(CONF_MODBUS_RETR_WAIT)			
                else:
                    break
            return regs_l
