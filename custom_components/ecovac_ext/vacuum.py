"""Support for Ecovacs Deebot Vacuums with Spot Area cleaning."""
import logging
import time
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
import base64
import struct
import lzma
import os
import zlib
from ozmo import VacBotCommand
import ast
import re
from threading import local
import concurrent.futures
import asyncio
import stringcase
import xml.etree.cElementTree as ET
import tempfile
import types
from datetime import datetime
from _datetime import timedelta
from PIL import Image

from homeassistant.components.vacuum import (
    SUPPORT_FAN_SPEED,
    STATE_CLEANING, STATE_RETURNING, STATE_DOCKED, STATE_ERROR,
    StateVacuumEntity)
from homeassistant.helpers.icon import icon_for_battery_level

from . import ECOVACS_DEVICES, CONF_SUPPORTED_FEATURES, ECOVACS_CONFIG
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_UNAVAILABLE,\
    EVENT_HOMEASSISTANT_STOP

from ozmo import (
    CHARGE_MODE_IDLE,
    CHARGE_MODE_RETURN,
    CHARGE_MODE_RETURNING,
    VACUUM_STATUS_OFFLINE,
    CLEAN_MODE_STOP,
    VacBot)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_platform

_LOGGER = logging.getLogger(__name__)

ATTR_ERROR = "error"
ATTR_COMPONENT_PREFIX = "component_"

STATE_CODE_TO_STATE = {
    CHARGE_MODE_IDLE: STATE_IDLE,
    
    CHARGE_MODE_RETURN: STATE_RETURNING,
    CHARGE_MODE_RETURNING: STATE_RETURNING,
    
    CLEAN_MODE_STOP: STATE_IDLE,
    
    VACUUM_STATUS_OFFLINE: STATE_UNAVAILABLE,
    
    'pause': STATE_PAUSED,
}

UPDATE_INTERVAL = 60 * 5

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Ecovacs vacuums."""
    vacuums = []
    for device in hass.data[ECOVACS_DEVICES]:
        vacuums.append(LiveMapEcovacsDeebotVacuum(hass, device, hass.data[ECOVACS_CONFIG][0]))
        
    _LOGGER.debug("Adding Ecovacs Deebot Vacuums to Hass: %s", vacuums)
    async_add_entities(vacuums, True)
    
    ## Register custom service for named zone cleaning
    platform = entity_platform.current_platform.get()
    
    platform.async_register_entity_service(
        "ecovacs_clean_zone",
        {
            vol.Required("zone"): cv.string
        },
        "async_clean_zone",
    )


class EcovacsDeebotVacuum(StateVacuumEntity):
    """Ecovacs Vacuums such as Deebot."""

    def __init__(self, hass, device: VacBot, config):
        _LOGGER.debug("CONFIG: %s", str(config))

        self.hass = hass

        """Initialize the Ecovacs Vacuum."""
        self.device = device
        if self.device.vacuum.get("nick", None) is not None:
            self._name = "{}".format(self.device.vacuum["nick"])
        else:
            # In case there is no nickname defined, use the device id
            self._name = "{}".format(self.device.vacuum["did"])

        self.clean_mode = 'auto'
        self._fan_speed = 'normal'
        self._error = None
        self._supported_features = config[CONF_SUPPORTED_FEATURES]
        _LOGGER.debug("Vacuum initialized: %s with features: %d", self.name, self._supported_features)

    async def async_added_to_hass(self) -> None:
        """Set up the event listeners now that hass is ready."""
        self.device.statusEvents.subscribe(lambda _: self.schedule_update_ha_state())
        self.device.batteryEvents.subscribe(lambda _: self.schedule_update_ha_state())
        self.device.lifespanEvents.subscribe(lambda _: self.schedule_update_ha_state())
        self.device.fanEvents.subscribe(self.on_fan_change)
        self.device.errorEvents.subscribe(self.on_error)

    def on_error(self, error):
        _LOGGER.info("vacuum error: %s", error)
        
        """Handle an error event from the robot.

        This will not change the entity's state. If the error caused the state
        to change, that will come through as a separate on_status event
        """
        if error == "no_error":
            self._error = None
        else:
            self._error = error

        self.hass.bus.fire(
            "ecovacs_error", {"entity_id": self.entity_id, "error": error}
        )
        self.schedule_update_ha_state()

    def on_fan_change(self, fan_speed):
        self._fan_speed = fan_speed
        self.schedule_update_ha_state()

    @property
    def should_poll(self) -> bool:
        """Return True if entity has to be polled for state."""
        return False

    @property
    def unique_id(self) -> str:
        """Return an unique ID."""
        return self.device.vacuum.get("did", None)

    @property
    def is_on(self):
        """Return true if vacuum is currently cleaning."""
        return self.device.is_cleaning

    @property
    def is_charging(self):
        """Return true if vacuum is currently charging."""
        return self.device.is_charging

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def supported_features(self):
        """Flag vacuum cleaner robot features that are supported."""
        return self._supported_features

    @property
    def status(self):
        """Return the status of the vacuum cleaner."""
        return self.device.vacuum_status
    
    @property
    def state(self):
        """Return the decoded status of the vacuum cleaner."""
        # The vacuum reverts back to an pause state after erroring out.
        # We want to keep returning an error until it has been cleared.
        if self._error:
            return STATE_ERROR
        elif self.device.is_charging:
            return STATE_DOCKED
        elif self.device.is_cleaning:
            return STATE_CLEANING
        elif self.device.vacuum_status is not None:
            try:
                return STATE_CODE_TO_STATE[self.device.vacuum_status]
            except KeyError:
                _LOGGER.error(
                    "STATE not supported: %s",
                    self.device.vacuum_status,
                )
                return None

    async def async_return_to_base(self, **kwargs):
        """Set the vacuum cleaner to return to the dock."""
        from ozmo import Charge

        self.hass.async_add_executor_job(self.device.run, Charge())

    @property
    def battery_icon(self):
        """Return the battery icon for the vacuum cleaner."""
        return icon_for_battery_level(
            battery_level=self.battery_level, charging=self.is_charging
        )

    @property
    def battery_level(self):
        """Return the battery level of the vacuum cleaner."""
        if self.device.battery_status is not None:
            return self.device.battery_status * 100

        return super().battery_level

    @property
    def fan_speed(self):
        """Return the fan speed of the vacuum cleaner."""
        if bool(self.supported_features & SUPPORT_FAN_SPEED):
            return self._fan_speed
        return 'normal'

    async def async_set_fan_speed(self, fan_speed, **kwargs):
        """Set fan speed."""
        from ozmo import SetCleanSpeed

        self.hass.async_add_executor_job(self.device.run, SetCleanSpeed(fan_speed))
        self._fan_speed = fan_speed
        
        await self.async_update_ha_state()

    @property
    def fan_speed_list(self):
        """Get the list of available fan speed steps of the vacuum cleaner."""
        from ozmo import FAN_SPEED_NORMAL, FAN_SPEED_HIGH

        return [FAN_SPEED_NORMAL, FAN_SPEED_HIGH]

    async def async_turn_on(self, **kwargs):
        """Turn the vacuum on and start cleaning."""
        from ozmo import Clean

        self.clean_mode = 'auto'
        self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='start'))

    async def async_turn_off(self, **kwargs):
        """Turn the vacuum off stopping the cleaning and returning home."""
        self.clean_mode = None
        await self.async_return_to_base()

    async def async_stop(self, **kwargs):
        """Stop the vacuum cleaner."""
        from ozmo import Clean

        self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='stop'))

    async def async_start(self):
        """Start, pause or resume the cleaning task."""
        if self.device.vacuum_status == 'pause':
            await self.async_resume()
        elif self.device.vacuum_status != 'pause':
            await self.async_turn_on()

    async def async_pause(self, **kwargs):
        """Stop the vacuum cleaner."""
        from ozmo import Clean

        self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='pause'))

    async def async_resume(self, **kwargs):
        """Stop the vacuum cleaner."""
        from ozmo import Clean

        self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='resume'))

    async def async_start_pause(self, **kwargs):
        """Start, pause or resume the cleaning task."""
        if self.device.vacuum_status == 'pause':
            await self.async_resume()
        elif self.device.vacuum_status != 'pause':
            await self.async_pause()

    async def async_clean_spot(self, **kwargs):
        """Perform a spot clean-up."""
        from ozmo import Clean

        self.clean_mode = 'spot'
        self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='start'))

    async def async_locate(self, **kwargs):
        """Locate the vacuum cleaner."""
        from ozmo import PlaySound

        self.hass.async_add_executor_job(self.device.run, PlaySound())

    async def async_send_command(self, command, params=None, **kwargs):
        """Send a command to a vacuum cleaner."""

        """
        {
          "entity_id": "vacuum.<ID>",
          "command": "spot_area",
          "params" : {
            "area": "0,2"
          }
        }
        
        or
        
        {
          "entity_id": "vacuum.<ID>",
          "command": "spot_area",
          "params" : {
            "map": "1580.0,-4087.0,3833.0,-7525.0"
          }
        }
		
		or
        
        Send command to edge clean.

        {
          "entity_id": "vacuum.<ID>",
          "command": "clean_edge",
        }
        """

        from ozmo import Edge

        if command == 'clean_edge':
            self.hass.async_add_executor_job(self.device.run, Edge())

        if command == 'spot_area':
            if 'area' in params:
                return await self.async_clean_area(params['area'])
            elif 'map' in params:
                return await self.async_clean_map(params['map'])

        if command == 'set_water_level':
            return await self.async_set_water_level(params['level'])

        self.hass.async_add_executor_job(self.device.run, VacBotCommand(command, params))

    async def async_clean_map(self, map_data, cleanings = '1'):
        from ozmo import Clean, SpotArea

        if not map_data:
            self.clean_mode = 'auto'
            self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='start'))
        else:
            self.clean_mode = 'spot_area'
            self.hass.async_add_executor_job(self.device.run, SpotArea(map_position=map_data, speed=self.fan_speed, action='start', cleanings=cleanings))

    async def async_clean_area(self, area):
        from ozmo import Clean, SpotArea

        if not area:
            self.clean_mode = 'auto'
            self.hass.async_add_executor_job(self.device.run, Clean(mode=self.clean_mode, speed=self.fan_speed, action='start'))
        else:
            self.clean_mode = 'spot_area'
            self.hass.async_add_executor_job(self.device.run, SpotArea(area=area, speed=self.fan_speed, action='start'))

    async def async_set_water_level(self, level):
        from ozmo import SetWaterLevel

        self.hass.async_add_executor_job(self.device.run, SetWaterLevel(level=level))

    @property
    def device_state_attributes(self):
        """Return the device-specific state attributes of this vacuum."""
        data = {}
        data[ATTR_ERROR] = self._error

        for key, val in self.device.components.items():
            attr_name = ATTR_COMPONENT_PREFIX + key
            data[attr_name] = int(val * 100)

        data["clean_mode"] = self.clean_mode

        return data


class LiveMapEcovacsDeebotVacuum(EcovacsDeebotVacuum):
    def __init__(self, hass, device: VacBot, config):
        """Initialize a generic camera."""
        super().__init__(hass, device, config)
        
        self.hass = hass
        
        self._thread_local = local()
        
        self._device = device
        

        self._custom_zones_update_timestamp = None
        self._custom_zones = config["custom_zones"]
        
        self._update_interval = 30
        self._update_lock = asyncio.Lock()
        
        self.updates_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="ecovas_ext_updates")
        self.pull_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="ecovas_ext_pull")
        
        self._stopped = False
        
        self._map_info = None
        self._map_info_timestamp = None
        
        self._trace_info = None
        self._trace_info_timestamp = None
        self._trace_points = None
        
        self._device_pos = None
        self._device_pos_timestamp = None
        
        self._charger_pos = None
        self._charger_pos_timestamp = None

        self._map_image = None
        
        self._camera_image = b"<svg/>"
        self._camera_image_timestamp = None
        self._camera_image_last_device_pos = None
        
        
        self._map_set_info = {
            'vw': None,
            'sa': None,
        }
        self._map_set_info_timestamp = {
            'vw': None,
            'sa': None,
        }
        self._map_set_data = {
            'vw': None,
            'sa': None,
        }
        self._current_map_set_type = None
        
        self._device_update_timestamp = None

        if self._device.vacuum.get('nick', None) is not None:
            self._name = '{}'.format(self._device.vacuum['nick'])
        else:
            # In case there is no nickname defined, use the device id
            self._name = '{}'.format(self._device.vacuum['did'])
          
        if not self._device.vacuum['iotmq']:
            self._device.xmpp.subscribe_to_ctls(self._handle_ctl)
        else:
            # Patch api responses handling (disable base64 patching for local logic and implement children handling)
            original_handle_ctl_api = self._device.iotmq._handle_ctl_api
            
            def convert_to_dict(xml):
                result = xml.attrib.copy()
                
                children = list(xml)
                if children:
                    result["#children"] = []
                    for child in list(xml):
                        result["#children"].append(convert_to_dict(child))
                        
                return result
                    
            def custom__handle_ctl_api(_self, action, message):
                _LOGGER.debug("Handling message with custom logic: %s" , message)
                # Invoke original handler
                original_handle_ctl_api(action, message)
                
                # handle local commands:
                if (not self._stopped) and (not message == {}):
                    xml = ET.fromstring(message['resp'])
                    resp = convert_to_dict(xml)
                    resp['event'] = stringcase.snakecase(action.name.replace("Get","",1))
                    
                    self._handle_ctl(resp)
                    

                    
            def custom__handle_ctl_mqtt(_self, client, userdata, message):
                message_string = str(message.payload.decode("utf-8"))
                _LOGGER.debug("Handling mqtt message with custom logic: %s" , message_string)
                
                # Invoke original handler
                _self._handle_ctl_mqtt(client, userdata, message)
                
                # handle local commands:
                if (not self._stopped):
                    xml = ET.fromstring(message_string)
                    
                    if ('td' in xml.attrib):
                        resp = convert_to_dict(xml)
                        resp['event'] = stringcase.snakecase(xml.attrib["td"])
                        
                        self._handle_ctl(resp)
            
            # Use a custom wrapper method to properly handle texts for local event handling for both API and MQTT.
            self._device.iotmq._handle_ctl_api = types.MethodType(custom__handle_ctl_api, self._device.iotmq)
            self._device.iotmq._on_message = types.MethodType(custom__handle_ctl_mqtt, self._device.iotmq)
            
        self._map_cache_directory_path = tempfile.mkdtemp(prefix='vacuum_ecovacs_map_cache_' + self._device.vacuum['did'])
    
    async def async_clean_zone(self, zone):
        """Set the Flo location to sleep mode."""
        
        zone_normalized = zone.lower().strip()
        
        zone_coords = next(iter([zone.get('points') for zone in self._custom_zones if zone.get('name').lower().strip() == zone_normalized]), None)
        
        if (zone_coords is None):
            raise Exception("Invalid zone name: " + zone)
        
        await self.async_clean_map(zone_coords)
    
    async def async_check_and_update_map(self, now):
        """Check if some data needs to be updated."""
        async with self._update_lock:
            if not self._stopped:
                update_futures = []
                if self._map_info_timestamp is None or time.time() - self._map_info_timestamp >= UPDATE_INTERVAL:
                    update_futures.append(self.updates_executor.submit(self._device.run, VacBotCommand('GetMapM')))
                    
                if self._trace_info_timestamp is None or time.time() - self._trace_info_timestamp >= UPDATE_INTERVAL:
                    update_futures.append(self.updates_executor.submit(self._device.run, VacBotCommand('GetTrM')))
        
                if self._device_pos_timestamp is None or time.time() - self._device_pos_timestamp >= UPDATE_INTERVAL:
                    update_futures.append(self.updates_executor.submit(self._device.run, VacBotCommand('GetPos')))
        
                if self._charger_pos_timestamp is None or time.time() - self._charger_pos_timestamp >= UPDATE_INTERVAL:
                    update_futures.append(self.updates_executor.submit(self._device.run, VacBotCommand('GetChargerPos')))
                
                map_sets_to_update = []
                for map_set_type in self._map_set_info:
                    if self._map_set_info_timestamp[map_set_type] is None or time.time() - self._map_set_info_timestamp[map_set_type] >= UPDATE_INTERVAL:
                        map_sets_to_update.append(map_set_type)
                
                if (map_sets_to_update):
                    update_futures.append(self.updates_executor.submit(self.update_map_sets, map_sets_to_update))
                
                def job_wait_futures():
                    for update_future in update_futures:
                        update_future.result()
                    
                    if (update_futures):
                        self.schedule_update_ha_state()
                
                await self.hass.async_add_executor_job(job_wait_futures)
                
    def update_map_sets(self, map_sets):
        for map_set_type in map_sets:
            _LOGGER.debug("Getting map set %s" , map_set_type)
            self._device.run(VacBotCommand('GetMapSet', {'tp':map_set_type}))
        
    def update_map(self):
        _LOGGER.debug('Updating ecovacs image.')
            
        grid_c = self._map_info['grid_columns']
        grid_r = self._map_info['grid_rows']
        piece_w = self._map_info['grid_piece_w']
        piece_h = self._map_info['grid_piece_h']
        
        map_w = grid_c * piece_w;
        map_h = grid_r * piece_h;
        
        clean_empty = True
        
        if (self._map_image is None) or (self._map_image.size[0] != map_w) or (self._map_image.size[1] != map_h):
            self._map_image = Image.new('RGBA', (map_w, map_h))
            clean_empty = False
        
        img = self._map_image
        
        # Pull all missing map pieces (concurrently)
        pull_futures = []
        pulled_hashes = []
        for grid_idx, grid_hash in enumerate(self._map_info['grid_piece_hashes']):
            piece_cache_file = os.path.join(self._map_cache_directory_path, 'map_cache_' + str(self._map_info['id']) + '_' + str(grid_hash))
            if (not os.path.exists(piece_cache_file)) and (not grid_hash in pulled_hashes):
                pulled_hashes.append(grid_hash)
                pull_futures.append(self.pull_executor.submit(self._device.run, VacBotCommand('PullMP', {'pid':str(grid_idx)})))
        
        # wait pulls to be completed
        for pull_future in pull_futures:
            pull_future.result()
        
        # Generate the map
        for grid_idx, grid_hash in enumerate(self._map_info['grid_piece_hashes']):
            piece_cache_file = os.path.join(self._map_cache_directory_path, 'map_cache_' + str(self._map_info['id']) + '_' + str(grid_hash))
            
            if (not os.path.exists(piece_cache_file)):
                # No map piece, maybe changed recently (in the case it should have been handled by 
                # the piece patch handler), skip the current grid position
                _LOGGER.warn('Missing grid piece cache for index %s (hash: %s).' % (grid_idx, grid_hash))
                continue

            piece_data = []
            with open(piece_cache_file, 'rb') as f:
                piece_data = f.read()
                
            self.draw_map_grid_piece(img, piece_data, grid_idx, clean_empty)
        
        self._map_info_timestamp = time.time()
        
    def draw_map_grid_piece(self, img, piece_data, grid_idx, clean_empty):
        grid_c = self._map_info['grid_columns']
        grid_r = self._map_info['grid_rows']
        piece_w = self._map_info['grid_piece_w']
        piece_h = self._map_info['grid_piece_h']
    
        img_w = img.size[1]
    
        x = int(grid_idx % grid_c) * piece_w
        y = int(grid_idx / grid_r) * piece_h
        
        for idx, value in enumerate(piece_data):
            lx = int(idx % piece_w)
            ly = int(idx / piece_h)
            
            # The map is bottom, left origin, but PIL is upper left: rotating coordinates by 90° counter-clockwise.
            mx = y + ly
            my = img_w - 1 - (x + lx)
            
            if value == 0x00:
                # Empty: empty
                if clean_empty:
                    img.putpixel((mx, my), 0)
            elif value == 0x01:
                # Floor: light blue
                img.putpixel((mx, my), (186, 218, 255, 255))
            elif value == 0x02:
                # Wall: dark blue
                img.putpixel((mx, my), (84, 147, 214, 255))
        
        self._map_info_timestamp = time.time()
    
    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        def stop(event: object) -> None:
            _LOGGER.debug("Ecovacs map stopping for %s." , self._device)
            self._stopped = True 
            
            self.updates_executor.shutdown()
            self.pull_executor.shutdown()
            
            _LOGGER.debug("Ecovacs map successfully stopped for %s." , self._device)
            
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
        
        self.hass.async_create_task(self.async_check_and_update_map(datetime.now()))
        
        async_track_time_interval(self.hass, self.async_check_and_update_map, timedelta(seconds=self._update_interval))

    
    @property
    def state_attributes(self):
        data = super().state_attributes or {}
        
        data['device_update_timestamp'] = self._device_update_timestamp
        data['custom_zone_update_timestamp'] = self._custom_zones_update_timestamp
        data['custom_zones'] = self._custom_zones
        data['device_pos'] = self._device_pos
        data['charger_pos'] = self._charger_pos
        data['trace_info_timestamp'] = self._trace_info_timestamp
        data['map_set_info_timestamp'] = self._map_set_info_timestamp
        data['map_info_timestamp'] = self._map_info_timestamp
        
        return data
    
    def get_trace_info(self):
        return self._trace_info
    
    def get_map_set_info(self):
        return self._map_set_info
    
    def get_map_info(self):
        return self._map_info

    def get_map_image(self):
        return self._map_image
    
    def decompress7zBase64Data(self, data):
        # Decode Base64
        data = base64.b64decode(data)
        
        # Get lzma output size (Android app handle it as little-endian signed int)
        length = struct.unpack('<i', data[5:5+4])[0]
        
        # Init the LZMA decompressor using the lzma header
        dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, None, [lzma._decode_filter_properties(lzma.FILTER_LZMA1, data[0:5])])
        
        # Decompress the lzma stream to get raw data
        return dec.decompress(data[9:], length)
        
    def _handle_ctl(self, ctl):
        _LOGGER.debug('Received event: %s (full data: %s)' % (ctl['event'], ctl))
    
        method = '_handle_' + ctl['event']
        if hasattr(self, method):
            getattr(self, method)(ctl)
        
    def _handle_map_m(self, event):
        map_info = {
            'id': str(event.get('i')),
            'grid_rows': int(event.get('r')),
            'grid_columns': int(event.get('c')),
            'grid_piece_w': int(event.get('w')),
            'grid_piece_h': int(event.get('h')),
            'grid_piece_hashes': event.get('m').split(','),
        }
        
        if (self._map_info != map_info):
            _LOGGER.debug('Updating map info. Old: %s; New: %s' % (self._map_info, map_info))
            self._map_info = map_info
            
            self.update_map()
            
            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()
            
        self._map_info_timestamp = time.time()
        
    def _handle_pull_m_p(self, event):
        map_id = str(event.get('i'))
        piece_data = self.decompress7zBase64Data(event.get('p'))
        crc = str(zlib.crc32(piece_data) & 0xffffffff)
        
        piece_cache_file = os.path.join(self._map_cache_directory_path, 'map_cache_' + map_id + '_' + crc)
    
        with open(piece_cache_file, 'w+b') as f:
            f.write(bytearray(piece_data))
        
        
    def _handle_map_p(self, event):
        # Map patched: update the patched piece
        piece_idx = int(event.get('pid'))
        map_id = str(event.get('i'))
        
        piece_data = self.decompress7zBase64Data(event.get('p'))
        crc = str(zlib.crc32(piece_data) & 0xffffffff)
        
        if (self._map_info is not None) and (self._map_info['id'] == map_id) and (self._map_info['grid_piece_hashes'][piece_idx] != crc):
            _LOGGER.debug('Updating map piece: %s' % (piece_idx))
        
            piece_cache_file = os.path.join(self._map_cache_directory_path, 'map_cache_' + map_id + '_' + crc)
        
            with open(piece_cache_file, 'w+b') as f:
                f.write(bytearray(piece_data))

            # Update the map hash if we have cached map info
            if self._map_info is not None:
                self._map_info['grid_piece_hashes'][piece_idx] = crc
                
            # Regenerate map piece portion if there is a map image
            if (not self._map_image is None):
                self.draw_map_grid_piece(self._map_image, piece_data, piece_idx, True)

            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()

    def add_trace_data(self, trace_data):
        if (len(trace_data) != 0) and (len(trace_data) % 5 == 0):
            for trace_group_idx in range(len(trace_data) // 5):
                trace_idx = trace_group_idx * 5
                
                data = trace_data[trace_idx + 4]
                
                self._trace_points.append({
                    'y': struct.unpack('<h', trace_data[trace_idx:trace_idx+2])[0],
                    'x': struct.unpack('<h', trace_data[trace_idx+2:trace_idx+4])[0],
                    'connected': not (((data >> 7) & 1) != 0),
                    'type': data & 1,
                })
            

    def _handle_tr_m(self, event):
        trace_info = {
            'id': str(event.get('trid')),
            'count': int(event.get('c')),
        }
        
        if (self._trace_info != trace_info):
            _LOGGER.debug('Updating trace info and points. Old: %s; New: %s' % (self._trace_info, trace_info))
            
            if (self._trace_points is None) or (self._trace_info is None) or (self._trace_info['id'] != trace_info['id']):
                _LOGGER.debug('Resetting trace points due new or changed trace id')
                self._trace_points = []
                
            self._trace_info = trace_info
            
            start_idx = len(self._trace_points)
            while (start_idx < trace_info['count']):
                end_idx = min(trace_info['count'] - 1, start_idx + 199)
                self._device.run(
                    VacBotCommand('GetTr', 
                        {
                            'id': trace_info['id'],
                            'tf': str(start_idx),  
                            'tt': str(end_idx)
                        }))
                start_idx = end_idx + 1
            
            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()
            
        self._trace_info_timestamp = time.time()
        
    def _handle_tr(self, event):
        self.add_trace_data(self.decompress7zBase64Data(event.get('tr')))
        

    def _handle_trace(self, event):
        trace_id = str(event.get('trid'))
        t_from = int(event.get('tf'))
        t_to = int(event.get('tt'))

        _LOGGER.debug('Handling points of received trace event')
        
        if (self._trace_points is None) or (t_from == 0) or ((self._trace_info is not None) and (self._trace_info['id'] != trace_id)):
            self._trace_points = []
        
        self._trace_info = {
            'id': trace_id,
            'count': t_to + 1,
        }

        while (len(self._trace_points) < t_from):
            chunk_idx = len(self._trace_points)
            self._device.run(
                VacBotCommand('GetTr', 
                    {
                        'trid': trace_id,
                        'tf': str(chunk_idx), 
                        'tt': str(min(t_from - 1, chunk_idx + 199)),
                    }
                )
            )
        
        self.add_trace_data(self.decompress7zBase64Data(event.get('tr')))
        
        self._trace_info_timestamp = time.time()
        self._device_update_timestamp = time.time()
        
        self.schedule_update_ha_state()

    def _handle_map_set(self, event):
        map_set_type = event.get('tp')
        
        map_set_info = {
            'id': str(event.get('msid')),
            'type': map_set_type,
            '#children': str(event.get('#children')),
        }
        
        # Always update map set info, as coordinate updates are not reflected in the map_set.
        #   - Old if content:  and self._map_set_info[map_set_type] != map_set_info
        if (map_set_type in self._map_set_info):
            _LOGGER.debug('Updating map set info for %s. Old: %s; New: %s' % (map_set_type, self._map_set_info[map_set_type], map_set_info))
            self._map_set_info[map_set_type] = map_set_info
            
            self._current_map_set_type = map_set_type 
            
            self._map_set_data[map_set_type] = {}

            pull_futures = []
            for child in (event.get('#children') or []):
                pull_futures.append(self.pull_executor.submit(
                    self.start_pull_m,
                    
                    map_set_info['id'],
                    map_set_type, 
                    str(child.get('mid'))
                ))
                
            for pull_future in pull_futures:
                pull_future.result()
                
            self._current_map_set_type = None
            
            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()
            
        self._map_set_info_timestamp[map_set_type] = time.time()
        
    
        
    def start_pull_m(self, msid, map_set_type, mid):
        self._thread_local.mid = mid
        self._device.run(
                    VacBotCommand('PullM', 
                        {
                            'msid': msid,
                            'tp': map_set_type, 
                            'mid': mid,
                            'seq': '0',
                        }
                    ))
        
        del self._thread_local.mid
        
    def _handle_pull_m(self, event):
        if (self._current_map_set_type):
            map_data = event.get('m')
            if (map_data[0] == '['):
                self._map_set_data[self._current_map_set_type][self._thread_local.mid] = ast.literal_eval(event.get('m'))
            else:
                self._map_set_data[self._current_map_set_type][self._thread_local.mid] = list(map(int, re.split(',|;', event.get('m'))))
        
        
    def _handle_pos(self, event):
        pos = event.get('p').split(',')
        
        device_pos = {
            'x': int(pos[0]),
            'y': int(pos[1]),
            'a': int(event.get('a')),
        }
        
        if (self._device_pos != device_pos):
            _LOGGER.debug('Updating pos. Old: %s; New: %s' % (self._device_pos, device_pos))
            
            self._device_pos = device_pos
            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()
            
        self._device_pos_timestamp = time.time()
    
    def _handle_charger_pos(self, event):
        pos = event.get('p').split(',')
        
        charger_pos = {
            'x': int(pos[0]),
            'y': int(pos[1]),
            'a': int(event.get('a')),
        }
        
        if (self._charger_pos != charger_pos):
            _LOGGER.debug('Updating charger. Old: %s; New: %s' % (self._charger_pos, charger_pos))
            
            self._charger_pos = charger_pos
            self._device_update_timestamp = time.time()
            
            self.schedule_update_ha_state()
            
        self._charger_pos_timestamp = time.time()