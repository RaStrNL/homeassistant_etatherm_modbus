<a href="https://www.buymeacoffee.com/qG6DdXgzah" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>
# Etatherm for Home Assistant
Repo contains custom integration for Etatherm heating (etatherm.cz) using Modbus protocol

## Configuration
There is no config flow yet.
Write to configuration.yaml

    climate:
    - platform: etatherm_modbus
      host: IP of your Eth1eC/D
      port: 502
      modbus_addr: 1 (It is same as J address of controller)
