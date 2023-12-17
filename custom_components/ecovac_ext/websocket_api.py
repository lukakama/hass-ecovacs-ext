import base64
import io
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

from homeassistant.components import websocket_api
from homeassistant.core import callback

from homeassistant.components.vacuum import DOMAIN as VACUUM_DOMAIN
from PIL import Image
from ozmo import VacBotCommand

_LOGGER = logging.getLogger(__name__)

def find_entity(hass, entity_id):
    component = hass.data.get(VACUUM_DOMAIN)
    
    return component.get_entity(entity_id)

@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/get_map",
        vol.Required("entity_id"): cv.entity_id,
    }
)
def websocket_handle_get_map(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    imgByteArr = io.BytesIO()
    image_box = None
    if (entity._map_image): 
        image_box = entity._map_image.getbbox()
        
        img = entity._map_image.crop(image_box)
        img = img.convert(mode='P', palette=Image.ADAPTIVE)
        
        img.save(imgByteArr, format='PNG', optimize=True)
    
    connection.send_result(
        msg["id"], 
        {
            "map_background_base64": base64.b64encode(imgByteArr.getvalue()).decode("ascii"),
            "map_background_left": image_box[0] if image_box else 0,
            "map_background_top": image_box[1] if image_box else 0,
            "map_background_right": image_box[2] if image_box else 0,
            "map_background_bottom": image_box[3] if image_box else 0,
            "map_width": entity._map_image.size[0] if entity._map_image else 0,
            "map_height": entity._map_image.size[1] if entity._map_image else 0,
        }
    )
    
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/get_map_set",
        vol.Required("entity_id"): cv.entity_id,
    }
)
def websocket_handle_get_map_set(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    connection.send_result(
        msg["id"], 
        {
            "map_set_info": entity._map_set_info,
            "map_set_data": entity._map_set_data,
        }
    )
    
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/get_trace",
        vol.Required("entity_id"): cv.entity_id,
    }
)
def websocket_handle_get_trace(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    connection.send_result(
        msg["id"], 
        {
            "trace_points": entity._trace_points,
        }
    )
    
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/clean_custom_rect",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("cleanings"): vol.All(vol.Coerce(int), vol.Range(min=1, max=2)),
        vol.Required("rect"): vol.All(cv.ensure_list, [vol.Coerce(float)]),
    }
)
async def async_websocket_handle_clean_custom_rect(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    
    await entity.async_clean_map(','.join(map(lambda val: str(round(val)), msg['rect'])), str(msg["cleanings"]))
    
    connection.send_result(msg["id"], {"success":True})
    
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/clean_rooms",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("rooms"): vol.All(cv.ensure_list, [cv.positive_int]),
    }
)
async def async_websocket_handle_clean_rooms(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await entity.async_clean_area(','.join(map(str,msg['rooms'])))
    
    connection.send_result(msg["id"], {"success":True})
 
   
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/add_wall",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("wall_data"): vol.All(cv.ensure_list, [vol.Coerce(float)]),
    }
)
async def async_websocket_handle_add_wall(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    
    
    await hass.async_add_executor_job(entity.device.run, 
        VacBotCommand("AddM", {
            'tp': 'vw',
            'msid': entity._map_set_info["vw"]["id"],
            'n': '',
            'm': '[' + ','.join(map(lambda val: str(round(val)), msg['wall_data'])) + ']',            
        }))
    
    hass.async_add_executor_job(entity.update_map_sets, ['vw'])
    
    connection.send_result(msg["id"], {"success":True})
    
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/edit_wall",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("wall"): cv.positive_int,
        vol.Required("wall_data"): vol.All(cv.ensure_list, [vol.Coerce(float)]),
    }
)
async def async_websocket_handle_edit_wall(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await hass.async_add_executor_job(entity.device.run, 
        VacBotCommand("UpdateM", {
            'tp': 'vw',
            'msid': str(entity._map_set_info["vw"]["id"]),
            'n': '',
            'm': [
                {
                    'mid': str(msg['wall']),
                    'm': '[' + ','.join(map(lambda val: str(round(val)), msg['wall_data'])) + ']' 
                }
            ],            
        }))
    
    hass.async_add_executor_job(entity.update_map_sets, ['vw'])
    
    connection.send_result(msg["id"], {"success":True})
   
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/remove_wall",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("wall"): cv.positive_int,
    }
)
async def async_websocket_handle_remove_wall(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await hass.async_add_executor_job(entity.device.run, 
        VacBotCommand("DelM", {
            'tp': 'vw',
            'msid': str(entity._map_set_info["vw"]["id"]),
            'mid': str(msg['wall']),
        }))
    
    hass.async_add_executor_job(entity.update_map_sets, ['vw'])
    
    connection.send_result(msg["id"], {"success":True})

@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/get_custom_zones",
        vol.Required("entity_id"): cv.entity_id,
    }
)
def async_websocket_handle_get_custom_zone(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    connection.send_result(
        msg["id"], 
        {
            "custom_zones": entity._custom_zones
        }
    )
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/add_custom_zone",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("custom_zone_name"): cv.string,
        vol.Required("custom_zone_data"): vol.All(cv.ensure_list, [vol.Coerce(float)]),
    }
)
async def async_websocket_handle_add_custom_zone(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await entity.add_custom_zone(msg['custom_zone_name'], msg['custom_zone_data'])
    
    connection.send_result(msg["id"], {"success":True})
    
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/edit_custom_zone",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("custom_zone"): cv.string,
        vol.Required("custom_zone_name"): cv.string,
        vol.Required("custom_zone_data"): vol.All(cv.ensure_list, [vol.Coerce(float)]),
    }
)
async def async_websocket_handle_edit_custom_zone(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await entity.edit_custom_zone(msg['custom_zone'], str(msg['custom_zone_name']), msg['custom_zone_data'])
    
    connection.send_result(msg["id"], {"success":True})
   
@websocket_api.async_response
@websocket_api.websocket_command( 
    {
        vol.Required("type"): "ecovacs/remove_custom_zone",
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("custom_zone"): cv.positive_int,
    }
)
async def async_websocket_handle_remove_custom_zone(hass, connection, msg):
    entity = find_entity(hass, msg["entity_id"])
    
    if entity is None:
        connection.send_error(
            msg["id"], "entity_not_found", "Entity not found"
        )
        return
    
    await entity.remove_custom_zone(msg['custom_zone'])
    
    connection.send_result(msg["id"], {"success":True})


@callback
def async_load_websocket_api(hass):
    """Set up the web socket API."""
    websocket_api.async_register_command(hass, websocket_handle_get_map)
    websocket_api.async_register_command(hass, websocket_handle_get_map_set)
    websocket_api.async_register_command(hass, websocket_handle_get_trace)
    
    websocket_api.async_register_command(hass, async_websocket_handle_clean_custom_rect)
    websocket_api.async_register_command(hass, async_websocket_handle_clean_rooms)
    
    websocket_api.async_register_command(hass, async_websocket_handle_add_wall)
    websocket_api.async_register_command(hass, async_websocket_handle_edit_wall)
    websocket_api.async_register_command(hass, async_websocket_handle_remove_wall)
    
    websocket_api.async_register_command(hass, async_websocket_handle_add_custom_zone)
    websocket_api.async_register_command(hass, async_websocket_handle_edit_custom_zone)
    websocket_api.async_register_command(hass, async_websocket_handle_remove_custom_zone)