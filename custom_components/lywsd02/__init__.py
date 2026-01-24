from __future__ import annotations

import logging
import struct
from datetime import datetime

from bleak import BleakClient

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType
from homeassistant.components import bluetooth

DOMAIN = "lywsd02"

_LOGGER = logging.getLogger(__name__)

_UUID_TIME = 'EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6'
_UUID_TEMO = 'EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6'

def get_localized_timestamp():
    """
    Récupère le timestamp actuel et y ajoute le décalage du fuseau horaire local.
    Cela permet d'envoyer 'l'heure locale' à l'appareil qui s'attend à un timestamp brut.
    """
    # Récupère l'heure actuelle avec les infos de fuseau horaire du système
    now = datetime.now().astimezone()
    # Récupère le décalage (offset) en secondes
    offset = now.utcoffset().total_seconds()
    # Retourne le timestamp UTC + le décalage
    return int(now.timestamp() + offset)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Based off https://github.com/h4/lywsd02
    """
    
    @callback
    async def set_time(call: ServiceCall) -> None:
        mac = call.data['mac'].upper()
        if not mac:
            _LOGGER.error(f"The 'mac' parameter is missing from service call: {call.data}.")
            return

        tz_offset = call.data.get('tz_offset', 0)

        # Utilisation de la méthode native de HA pour trouver le device Bluetooth
        ble_device = bluetooth.async_ble_device_from_address(
            hass,
            mac,
            connectable=True
        )

        if not ble_device:
            _LOGGER.error(f"Could not find '{mac}'.")
            return

        _LOGGER.info(f"Found '{ble_device}' - Attempting to update time.")

        temo_set = False
        ckmo_set = False
        
        # Gestion de l'unité de température (C/F)
        temo = call.data.get('temp_mode', '') or "x"
        temo = temo.upper()
        _LOGGER.debug(f"temo var: {temo}")

        data_temp_mode = None
        if temo in 'CF':
            data_temp_mode = struct.pack('B', (0x01 if temo == 'F' else 0xFF))
            _LOGGER.debug(f"Will set temp_mode")
            temo_set = True

        # Gestion du mode 12h/24h
        ckmo = call.data.get('clock_mode', 0)
        _LOGGER.debug(f"ckmo var: {ckmo}")
        
        data_clock_mode = None
        if ckmo in [12, 24]:
            # 0xaa pour 12h, 0x00 pour 24h (selon la logique originale)
            data_clock_mode = struct.pack('IHB', 0, 0, 0xaa if ckmo == 12 else 0x00)
            _LOGGER.debug(f"Will set clock_mode")
            ckmo_set = True

        tout = int(call.data.get('timeout', 60))
        
        async with BleakClient(ble_device, timeout=tout) as client:
            timestamp = int(
                call.data.get('timestamp') or get_localized_timestamp()
            )

            # Envoi de l'heure
            data = struct.pack('Ib', timestamp, tz_offset)
            await client.write_gatt_char(_UUID_TIME, data)
            
            # Envoi du mode Température si demandé
            if temo_set and data_temp_mode:
                await client.write_gatt_char(_UUID_TEMO, data_temp_mode)
            
            # Envoi du mode Horloge si demandé (note: utilise le même UUID que l'heure sur ce device)
            if ckmo_set and data_clock_mode:
                await client.write_gatt_char(_UUID_TIME, data_clock_mode)

        _LOGGER.info(f"Done - refreshed time on '{mac}' to '{timestamp}' with offset of '{tz_offset}' hours.")

    hass.services.async_register(DOMAIN, 'set_time', set_time)

    return True
