# Etatherm for Home Assistant
Repo contains custom integration for Etatherm heating (etatherm.cz) using Modbus protocol

## Configuration
There is no config flow yet.
Write to configuration.yaml

climate:
- platform: etatherm
  host: IP of your Eth1eC/D
  port: 502
  modbus_addr: 1 (It is same as J address of controller)
