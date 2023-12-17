"""Support for IP Cameras."""
import ast
import base64
import concurrent.futures
import io
import logging
import lzma
import os
import re
import struct
import tempfile
from threading import local
import time
import types
import xml
import zlib

from datetime import datetime

from PIL import Image
from homeassistant.components.camera import (
    Camera,
)
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
)
import stringcase

from . import ECOVACS_DEVICES

import xml.etree.cElementTree as ET
from ozmo import VacBotCommand
from homeassistant.helpers.event import async_track_time_interval
from _datetime import timedelta
import asyncio


UPDATE_INTERVAL = 60 * 5

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up a generic IP Camera."""
    vacuums = []
    #for device in hass.data[ECOVACS_DEVICES]:
    #    vacuums.append(EcovacsMapCamera(hass, config, device))

    def stop(event: object) -> None:
        for vacuum in vacuums:
            vacuum.shutdown()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)

    async_add_entities(vacuums)
    
class EcovacsMapCamera(Camera):
    """A generic implementation of an IP camera."""

    def __init__(self, hass, config, device):
        """Initialize a generic camera."""
        super().__init__()
        
        self.hass = hass
        
        self._thread_local = local()
        
        self._device = device
        
        self._update_interval = 30
        self._update_lock = asyncio.Lock()
        
        self.updates_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
        self.pull_executor = concurrent.futures.ThreadPoolExecutor(max_workers=15)
        
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
                
                children = xml.getchildren()
                if children:
                    result["#children"] = []
                    for child in xml.getchildren():
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
            
            # Use a custom wrapper method to properly handle texts for local event handling forboth API and MQTT.
            self._device.iotmq._handle_ctl_api = types.MethodType(custom__handle_ctl_api, self._device.iotmq)
            self._device.iotmq._on_message = types.MethodType(custom__handle_ctl_mqtt, self._device.iotmq)
            
        self._map_cache_directory_path = tempfile.mkdtemp(prefix='ecovacs_map_cache_' + self._device.vacuum['did'])
        
        self._frame_interval = 1 / 2
        self._supported_features = 0
        self.content_type = 'image/svg+xml'
        #self.content_type = 'image/png'
    
    def shutdown(self):
        _LOGGER.debug("Ecovacs map stopping for %s." , self._device)
        self._stopped = True 
        
        self.updates_executor.shutdown()
        self.pull_executor.shutdown()
        
        _LOGGER.debug("Ecovacs map successfully stopped for %s." , self._device)

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        self.hass.async_create_task(self.async_check_and_update_map(datetime.now()))
        
        async_track_time_interval(self.hass, self.async_check_and_update_map, timedelta(seconds=self._update_interval))


    @property
    def is_recording(self):
        """Return true if the device is recording."""
        return True
            
    @property
    def supported_features(self):
        """Return supported features for this camera."""
        return self._supported_features

    @property
    def frame_interval(self):
        """Return the update map interval."""
        return self._frame_interval

    def camera_image(self):
        """Return bytes of camera image."""
        if not self._stopped:
            if ((self._device_update_timestamp is not None) and 
                    ((self._camera_image_timestamp is None) 
                        or (self._camera_image_timestamp <= self._device_update_timestamp)
                        or (self._camera_image_last_device_pos != self._device_pos))):
                _LOGGER.debug('Generating camera image. Image last update: %s; Device last update: %s' % (self._camera_image_timestamp, self._device_update_timestamp))
                self.generate_camera_image_svg()
            
        return self._camera_image
        
    @property
    def should_poll(self):
        return False
        
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
        
        # Pull all missing map pieces (TODO: concurrently)
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
        
    def generate_camera_image_svg(self):
        if (self._map_image is None):
            return
            
        # Map increase scale to improve image resolution
        map_scale = 3
        
        # Factor of devices resolution (devices use 50 times higher resolution compared to the map), adapted to map scale
        device_map_scale = 0.02 * map_scale
        
        map_margin = 6
        
        # Element offsets for drawing circles
        device_r = (4 * map_scale)
        charger_r = (1 * map_scale)
        

        img = self._map_image
        
        # Crop empty spaces
        image_box = img.getbbox()

        # Calculate the base map center with crop offset 
        cropped_map_center_x = img.size[0] / 2 - image_box[0]
        cropped_map_center_y = img.size[1] / 2 - image_box[1]
        
        
        img = img.crop(image_box)
        
        img = img.convert(mode='P', palette=Image.ADAPTIVE)

        imgByteArr = io.BytesIO() 
        img.save(imgByteArr, format='PNG', optimize=True)

        # Calculate scaled full map size with margins
        map_size_w = (img.size[0] * map_scale) + (map_margin * 2)
        map_size_h = (img.size[1] * map_scale) + (map_margin * 2)
        
        # Init map
        svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width = str(map_size_w), height = str(map_size_h), viewBox = "0 0 %g %g" % (map_size_w, map_size_h))
        
        # Add defs (gradients)
        defs = ET.SubElement(svg, "defs")
        radialGradient = ET.SubElement(defs, "radialGradient", id="device_bg", cx="50%", cy="50%", r="50%", fx="50%", fy="50%")
        ET.SubElement(radialGradient, "stop", offset="70%", style="stop-color:#0000FF;")
        ET.SubElement(radialGradient, "stop", offset="97%", style="stop-color:#0000FF00;")
        
        # Add styles
        style_el = ET.SubElement(svg, "style", type="text/css")
        style_el.text = """
            .room:hover {
                fill-opacity: 0.5 !important;
            }
        """
        
        # Draw png map
        map_el = ET.SubElement(svg, "image", x = str(map_margin), y = str(map_margin))
        map_el.attrib['href'] = "data:image/png;base64," + base64.b64encode(imgByteArr.getvalue()).decode("ascii")
        map_el.attrib['width'] = "%g" % (img.size[0] * map_scale)
        map_el.attrib['height'] = "%g" % (img.size[1] * map_scale)
        map_el.attrib['style'] = "image-rendering: pixelated"

        # Draw devices and trace points
        mapMiddleX = (cropped_map_center_x * map_scale) + map_margin
        mapMiddleY = (cropped_map_center_y * map_scale - map_scale) + map_margin #0,0 offset on the top
        
        colors = ['violed', 'green', 'magenta', 'purple', 'maroon']
        
        for map_set_type in self._map_set_info:
            if (map_set_type in self._map_set_data):
                for element_idx, element_map_id in enumerate(self._map_set_data[map_set_type]):
                    map_set_element =  self._map_set_data[map_set_type][element_map_id]
                    style = None
                    
                    svg_id = "%s_%s" % (map_set_type, element_map_id)
                    if (map_set_type == 'vw'):
                        style = "fill:red;fill-opacity:0.2;stroke:red;stroke-width:1;stroke-dasharray:3,3;pointer-events:none"
                    elif (map_set_type == 'sa'):
                        style = "fill:" + colors[element_idx % len(colors)] + ";fill-opacity:0.2;stroke:none"
                    points = []
                    for idx in range(len(map_set_element) // 2):
                        p_idx = idx * 2
                        posX = round(mapMiddleX + (map_set_element[p_idx] * device_map_scale), 0)
                        posY = round(mapMiddleY - (map_set_element[p_idx + 1] * device_map_scale), 0)
                        points.append("%g,%g"  % (posX, posY))  
                    
                    _LOGGER.debug('Map data for type %s: %s' % (map_set_type, points))
                    
                    map_element = ET.SubElement(svg, "polygon", id = svg_id, points = ' '.join(points), style = style)
                    if (map_set_type == 'sa'):
                        map_element.attrib['class'] = "room"
                        map_element.attrib['ondblclick'] = "alert('clicked ' + this.id)"
    
        if (self._trace_points):
            path_data = []

            last_rPosX = None
            last_rPosY = None
            current_command  = None
            for trace in self._trace_points:
                rPosX = round(mapMiddleX + (trace['y']  * device_map_scale * 10), 0)
                rPosY = round(mapMiddleY - (trace['x']  * device_map_scale * 10), 0)
                
                if trace['connected']:
                    if (last_rPosX is not None) and (last_rPosY is not None):
                        if (last_rPosX != rPosX) or (last_rPosY != rPosY):
                            if (last_rPosX == rPosX):
                                if (current_command != 'v'):
                                    current_command = 'v'
                                    path_data.append(current_command)
                                path_data.append("%g" % (round(rPosY - last_rPosY, 0)))
                            elif (last_rPosY == rPosY):
                                if (current_command != 'h'):
                                    current_command = 'h'
                                    path_data.append(current_command)
                                path_data.append("%g" % (round(rPosX - last_rPosX, 0)))
                            else:
                                if (current_command != 'l'):
                                    current_command = 'l'
                                    path_data.append(current_command)
                                path_data.append("%g" % (round(rPosX - last_rPosX, 0)))
                                path_data.append("%g" % (round(rPosY - last_rPosY, 0)))
                    else:
                        if (current_command != 'L'):
                            current_command = 'L'
                            path_data.append(current_command)
                        path_data.append("%g" % (rPosX))
                        path_data.append("%g" % (rPosY))
                else:
                    if (last_rPosX is not None) and (last_rPosY is not None):
                        if (current_command != 'm'):
                            current_command = 'm'
                            path_data.append(current_command)
                        path_data.append("%g" % (round(rPosX - last_rPosX, 0)))
                        path_data.append("%g" % (round(rPosY - last_rPosY, 0)))
                    else:
                        if (current_command != 'M'):
                            current_command = 'M'
                            path_data.append(current_command)
                        path_data.append("%g" % (rPosX))
                        path_data.append("%g" % (rPosY))
                last_rPosX = rPosX
                last_rPosY = rPosY
            
            if (path_data):
                # Generate and compact path commands removing non digit pre and post whitespaces
                string_path_data = ' '.join(path_data)
                string_path_data = re.sub(r' ([^0-9 ])', lambda m: m.group(1), string_path_data)
                string_path_data = re.sub(r'([^0-9 ]) ', lambda m: m.group(1), string_path_data)
                
                
                trace_el = ET.SubElement(svg, "path", 
                                         d = string_path_data, 
                                         stroke = "white", 
                                         fill = "none",
                                         style = "pointer-events: none")
                trace_el.attrib['stroke-width'] = str(2)
                trace_el.attrib['stroke-linejoin'] = "round"

        
        if (self._device_pos):
            posX = round(mapMiddleX + (self._device_pos['x'] * device_map_scale), 3)
            posY = round(mapMiddleY - (self._device_pos['y'] * device_map_scale), 3)
            
            last_posX = posX
            last_posY = posY
            if self._camera_image_last_device_pos is not None:
                last_posX = round(mapMiddleX + (self._camera_image_last_device_pos['x'] * device_map_scale), 3)
                last_posY = round(mapMiddleY - (self._camera_image_last_device_pos['y'] * device_map_scale), 3)
            
            _LOGGER.debug('Device position: %s, %s' % (posX, posY))
            
            
            circle_el = ET.SubElement(svg, "circle", 
                                      cx = str(last_posX), 
                                      cy = str(last_posY), 
                                      r = str(device_r), 
                                      fill = "url(#device_bg)",
                                      style = "pointer-events: none")
            if last_posX != posX or last_posY != posY:
                ET.SubElement(circle_el, "animateTransform", 
                        attributeName = "transform", 
                        type="translate",
                        dur="%gs" % (self._frame_interval),
                        to="%g %g" % (round(posX - last_posX, 3), round(posY - last_posY, 3)),
                        repeatCount="0",
                        fill="freeze")
                
            circle_el = ET.SubElement(svg, "circle", 
                                      cx = str(last_posX), 
                                      cy = str(last_posY), 
                                      r = str(device_r * 0.68), 
                                      stroke = "white", 
                                      fill = "blue",
                                      style = "pointer-events: none")
            circle_el.attrib['stroke-width'] = str(1)
            if last_posX != posX or last_posY != posY:
                ET.SubElement(circle_el, "animateTransform", 
                        attributeName = "transform", 
                        type="translate",
                        dur="%gs" % (self._frame_interval),
                        to="%g %g" % (posX - last_posX, posY - last_posY),
                        repeatCount="0",
                        fill="freeze")
            
            self._camera_image_last_device_pos = self._device_pos.copy()
            
        else:
            self._camera_image_last_device_pos = None
            
        if (self._charger_pos):
            posX = round(mapMiddleX + (self._charger_pos['x'] * device_map_scale), 3)
            posY = round(mapMiddleY - (self._charger_pos['y'] * device_map_scale) - (device_r + 1), 3)
            
            _LOGGER.debug('Charger position: %s, %s' % (posX, posY))
            
            circle_el = ET.SubElement(svg, "circle", 
                                      cx = str(posX), 
                                      cy = str(posY), 
                                      r = str(charger_r), 
                                      stroke = "green", 
                                      fill = "green",
                                      style = "pointer-events: none")
            circle_el.attrib['stroke-width'] = str(2)

        image_svg = ET.tostring(svg)
        
        #_LOGGER.debug("xml: %s" , image_svg)
    
        self._camera_image = image_svg
        self._camera_image_timestamp = time.time()

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
        
        if (map_set_type in self._map_set_info and self._map_set_info[map_set_type] != map_set_info):
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
        
    
    @property
    def name(self):
        """Return the name of this device."""
        return self._name
