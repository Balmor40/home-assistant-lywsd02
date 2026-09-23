from __future__ import annotations

import logging
import struct
from datetime import datetime

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.components import bluetooth

DOMAIN = "lywsd02"

_LOGGER = logging.getLogger(__name__)

_UUID_TIME = 'EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6'
_UUID_TEMO = 'EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6'

def get_localized_timestamp():

    #Récupère le timestamp actuel et y ajoute le décalage du fuseau horaire local.
    #Cela permet d'envoyer 'l'heure locale' à l'appareil qui s'attend à un timestamp brut.

    # Récupère l'heure actuelle avec les infos de fuseau horaire du système
    now = datetime.now().astimezone()
    # Récupère le décalage (offset) en secondes
    # (utcoffset() ne renvoie jamais None après astimezone(), le "or" rassure Pylance)
    offset = (now.utcoffset() or timedelta(0)).total_seconds()
    # Retourne le timestamp UTC + le décalage
    return int(now.timestamp() + offset)

def parse_display(value) -> tuple[int, int] | None:

    #Convertit la valeur 'display' ("0930", "09:30" ou 930) en (heures, minutes).
    #L'horloge ne sait afficher qu'une heure : HH doit être entre 00 et 23, MM entre 00 et 59.

    digits = str(value).strip().replace(':', '')
    if not digits.isdecimal() or len(digits) > 4:
        return None
    # Complète à 4 chiffres (YAML peut transformer "0930" en nombre 930)
    digits = digits.zfill(4)
    hours, minutes = int(digits[:2]), int(digits[2:])
    if hours > 23 or minutes > 59:
        return None
    return hours, minutes

def get_display_timestamp(hours: int, minutes: int) -> int:

    #Timestamp du jour courant à HH:MM:00, pour que l'horloge affiche "HHMM".
    #Les secondes à 0 laissent la valeur affichée une minute complète avant qu'elle n'avance.

    now = get_localized_timestamp()
    return now - now % 86400 + hours * 3600 + minutes * 60

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Based off https://github.com/h4/lywsd02
    """

    async def set_time(call: ServiceCall) -> None:
        mac = call.data['mac'].upper()
        if not mac:
            _LOGGER.error(f"The 'mac' parameter is missing from service call: {call.data}.")
            return

        tz_offset = call.data.get('tz_offset', 0)

        # Affichage de 4 chiffres au choix à la place de l'heure réelle
        display = call.data.get('display')
        display_hm = None
        if display not in (None, ''):
            display_hm = parse_display(display)
            if display_hm is None:
                _LOGGER.error(
                    f"Invalid 'display' value '{display}': expected 4 digits HHMM "
                    f"with HH between 00 and 23 and MM between 00 and 59."
                )
                return

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

        # A plain BleakClient regularly fails on the first attempt when the
        # device is reached through an ESPHome/Shelly Bluetooth proxy rather
        # than a local adapter. establish_connection retries and handles the
        # proxy's connection slots; `timeout` is forwarded to the client.
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            mac,
            timeout=tout,
        )
        try:
            if display_hm is not None:
                # Le décalage horaire est ignoré pour afficher exactement les chiffres demandés
                timestamp = get_display_timestamp(*display_hm)
                tz_offset = 0
            else:
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
                # 12/24-hour switching writes a 7-byte clock-format value to the
                # time characteristic. This is validated against a Mi Home app
                # capture on the LYWSD02MMC (0xAA => 12h, 0x00 => 24h, see #10),
                # but on the plain LYWSD02 the same characteristic is a fixed
                # 5-byte time attribute and rejects it with "Invalid attribute
                # length". Treat a rejection as "unsupported on this model" and
                # warn rather than failing the call - the time is already set.
                try:
                    await client.write_gatt_char(_UUID_TIME, data_clock_mode)
                except BleakError as err:
                    _LOGGER.warning(
                        "clock_mode (12/24-hour) could not be set on '%s': it is "
                        "only supported on the LYWSD02MMC and this device "
                        "rejected the write (%s). The time was set successfully "
                        "- remove the 'clock_mode' parameter to silence this "
                        "warning.",
                        mac, err,
                    )
        finally:
            await client.disconnect()

        if display_hm is not None:
            _LOGGER.info(f"Done - '{mac}' now displays '{display_hm[0]:02d}:{display_hm[1]:02d}'.")
        else:
            _LOGGER.info(f"Done - refreshed time on '{mac}' to '{timestamp}' with offset of '{tz_offset}' hours.")

    hass.services.async_register(DOMAIN, 'set_time', set_time)

    return True
