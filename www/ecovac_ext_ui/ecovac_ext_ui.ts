/*
import {LitElement, html, svg, css} from 'lit-element';
const LitElementOld = Object.getPrototypeOf(
	customElements.get("ha-panel-lovelace")
);
*/


import "@material/mwc-fab";

import {
	LitElement,
	html,
	css,
	svg,
	customElement,
	property,
	CSSResult,
	TemplateResult,
	PropertyValues,
	internalProperty,
  } from "lit-element";

@customElement('ecovacs-card')
export class TestCard extends LitElement {
	@property()
	config:any = null

	
	@property({type: Array})
	rooms:any = null;
	@property({type: Array})
	walls:any = null;

	@property({type: Array})
	selectedRooms:any = null

	@property({type: Array})
	path_points:any = null

	@property({type: Array})
	map_background_base64:any = null;
	@property({type: Array})
	map_background_top:any = null;
	@property({type: Array})
	map_background_bottom:any = null;
	@property({type: Array})
	map_background_left:any = null;
	@property({type: Array})
	map_background_right:any = null;

	@property({type: Array})
	map_width:any = null;
	@property({type: Array})
	map_height:any = null;

	@property({type: Array})
	selectedMode:any = null;
	@property({type: Array})
	vacuumZonedCleanupRepeats:any = null;

	@property({type: Array})
	drawingZone:any = null;
	@property({type: Array})
	drawingZoneStartPoint:any = null;
	@property({type: Array})
	drawingZoneEndPoint:any = null;
	@property({type: Array})
	drawingZoneAttr:any = null;

	@property({type: Array})
	wallMode:any = null;
	@property({type: Array})
	drawingWallStartPoint:any = null;
	@property({type: Array})
	drawingWallEndPoint:any = null;
	@property({type: Array})
	drawingWallAttr:any = null;

	@property({type: Array})
	viewportOffsetX:any = null;
	@property({type: Array})
	viewportOffsetY:any = null;
	@property({type: Array})
	viewportScale:any = null;
	
	coordination_scale: number;
	svg: any;
	pt: any;
	device_pos: { x: number; y: number; };
	charger_pos: { x: number; y: number; };
	trace_info_timestamp: any;
	map_set_info_timestamp: any;
	map_info_timestamp: any;
	device_update_timestamp: any;
	modes: Map<any, any>;
	selectedElementId: any;
	moveOffset: any;
	transform: any;
	selectedWallId: any;
	drawingNewWall: boolean;
	movingMap: boolean;
	pinchingMap: boolean;
	pinchDistance: number;
	pinchCenter: number[];
	_hass: any;
	shadowRoot: any;

	constructor() {
		super();

		this.svg = null;
		this.pt = null;
		
		this.device_pos = {
			x: 0,
			y: 0,
		};
		this.charger_pos = {
			x: 0,
			y: 0,
		};
		this.trace_info_timestamp = null;
		this.map_set_info_timestamp = null;
		this.map_info_timestamp = null;

		this.device_update_timestamp = null;
		
		this.path_points = [];

		this.rooms = [];
		this.walls = [];

		this.map_background_base64 = null;
		this.map_background_top = null;
		this.map_background_bottom = null;
		this.map_background_left = null;
		this.map_background_right = null;

		this.map_width = 0;
		this.map_height = 0;

		this.selectedRooms = [];

		this.coordination_scale = 0.02;


		this.drawingZone = false;
		this.drawingZoneStartPoint = null;
		this.drawingZoneEndPoint = null;
		this.drawingZoneAttr = null;


		this.selectedMode = "map";

		this.vacuumZonedCleanupRepeats = 1;

		this.modes = new Map();
        this.modes.set("map", "Mappa");
		this.modes.set("rooms", "Pulizia Stanze");
		this.modes.set("zoned_cleanup", "Pulizia Zona");
		this.modes.set("walls", "Modifica muri");
		
		this.selectedElementId = null;
		this.moveOffset = null;
		this.transform = null;

		this.wallMode = "edit";
		this.selectedWallId = null;
		this.drawingWallStartPoint = null;
		this.drawingWallEndPoint = null;
		this.drawingWallAttr = null;

		this.drawingNewWall = false;

		this.movingMap = false;

		this.viewportOffsetX = 0;
		this.viewportOffsetY = 0;
		this.viewportScale = 1;

		this.pinchingMap = false;
		this.pinchDistance = 0;
		this.pinchCenter = [0, 0];
	}
	
	@property({ attribute: false })	
	set hass(hass: any) {
        this._hass = hass;
		  
		const entityId = this.config.entity;
		
		const stateObj = hass.states[entityId];

		if (!stateObj) {
			throw new Error(`Entity ${entityId} not found`);
		}
		
		const attributes = stateObj.attributes;

		if (attributes['device_update_timestamp'] != this.device_update_timestamp ||
				attributes['device_pos'] != this.device_pos ||
				attributes['charger_pos'] != this.charger_pos ||
				attributes['trace_info_timestamp'] != this.trace_info_timestamp ||
				attributes['map_set_info_timestamp'] != this.map_set_info_timestamp ||
				attributes['map_info_timestamp'] != this.map_info_timestamp) {
			this.updateMap();
		}
    }

	setConfig(config) {
		if (!config.entity) {
			throw new Error('You need to define an entity');
		}
		this.config = config;
	}

	// The height of your card. Home Assistant uses this to automatically
	// distribute all cards over the available columns.
	getCardSize() {
		return 3;
	}

	
	updateMap() {
		const entityId = this.config.entity;
		  
		const stateObj = this._hass.states[entityId];
	  
		const attributes = stateObj.attributes;

		this.device_pos = attributes['device_pos'];
		this.charger_pos = attributes['charger_pos'];

		if (attributes['device_update_timestamp'] != this.device_update_timestamp) {
			this.map_info_timestamp = attributes['map_info_timestamp'];
			
			this._hass.callWS({
				type: 'ecovacs/get_map',
				entity_id: this.config.entity,
			}).then(response => {
				this.map_background_base64 = response["map_background_base64"];
				this.map_background_top = response["map_background_top"];
				this.map_background_bottom = response["map_background_bottom"];
				this.map_background_left = response["map_background_left"];
				this.map_background_right = response["map_background_right"];

				this.map_width = response["map_width"];
				this.map_height = response["map_height"];
			});
		}

		if (attributes['device_update_timestamp'] != this.device_update_timestamp) {
			this.map_set_info_timestamp = attributes['map_set_info_timestamp'];
			this._hass.callWS({
				type: 'ecovacs/get_map_set',
				entity_id: this.config.entity,
			}).then(response => {
				const rooms:Array<any> = [];
				const walls:Array<any> = [];

				const map_set_info = response.map_set_info;
				const map_set_data = response.map_set_data;

				for (let map_set_type in  map_set_info) {
					if (map_set_type in map_set_data) {
						for (let element_map_id in map_set_data[map_set_type]) {
							let map_set_element =  map_set_data[map_set_type][element_map_id]

							let points:any = [];
							for (let idx = 0; idx < map_set_element.length; idx++) {
								if (idx != 0) {
									if (idx % 2 == 0) {
										points.push(",");
									} else {
										points.push(" ");
									}
								}
								points.push(map_set_element[idx]);	
							}

							if (map_set_type == "sa") {
								rooms.push({
									"id": `${map_set_type}_${element_map_id}`,
									"mid": element_map_id,
									"points": points.join(""),
								});
							} else {
								walls.push({
									"id": `${map_set_type}_${element_map_id}`,
									"mid": element_map_id,
									"points": points.join(""),
								});
							}

						};
					}
				};
				this.rooms = rooms;
				this.walls = walls;

			});
		}

		if (attributes['device_update_timestamp'] != this.device_update_timestamp 
				&& attributes['trace_info_timestamp'] != this.trace_info_timestamp) {
			this.trace_info_timestamp = attributes['trace_info_timestamp'];

			this._hass.callWS({
				type: 'ecovacs/get_trace',
				entity_id: this.config.entity,
			}).then(response => {
				const trace_points = response.trace_points;

				const path_points:Array<String> = [];
				trace_points.forEach(trace => {
					if (trace['connected']) {
						path_points.push("L");
					} else {
						path_points.push("M");
					}
					path_points.push(trace["x"])
					path_points.push(trace["y"])
				});
				this.path_points = path_points.join(" ");
			});
		}

		this.device_update_timestamp = attributes['device_update_timestamp'];
	}

	
	handleRoomClick(e) {
		const id = e.target.id;
		if (this.selectedMode == "rooms") {
			if (this.selectedRooms.indexOf(id) != -1) {
				this.selectedRooms.splice(this.selectedRooms.indexOf(id), 1);

			} else {
				this.selectedRooms.push(id);
			}

			this.requestUpdate();
		}
	}
	requestUpdate() {
		throw new Error("Method not implemented.");
	}

	handleWallClick(e) {
		const id = e.target.id;
		if (this.selectedMode == "walls") {
			this.selectedWallId = id;

			const points = e.target.points;

			this.drawingWallStartPoint = [points[0].x, points[0].y] ;
			this.drawingWallEndPoint = [points[2].x, points[2].y];

			this.updateDrawingWall();
		}
	}
	

	addWall() {
		this.wallMode = 'add';
	}

	cancelWallChange() {
		this.wallMode = "edit";

		this.selectedWallId = null;
		this.drawingWallStartPoint = null;
		this.drawingWallEndPoint = null;
		this.drawingWallAttr = null;
	}


	confirmWallChange() {
		const wallData = [
			this.drawingWallStartPoint[0], this.drawingWallStartPoint[1],
			this.drawingWallStartPoint[0], this.drawingWallEndPoint[1],
			this.drawingWallEndPoint[0], this.drawingWallEndPoint[1],
			this.drawingWallEndPoint[0], this.drawingWallStartPoint[1],
		];

		if (this.selectedWallId == "newWall") {
			this._hass.callWS({
				type: 'ecovacs/add_wall',
				entity_id: this.config.entity,
				wall_data: wallData,
			}).then(() => {
				// Pre-save the new wall 
				this.walls.push({
					"id": 'vw_' + this.walls.length,
					"mid": '' + this.walls.length,
					"points": this.drawingWallAttr,
				})

				this.wallMode = "edit";
				this.selectedWallId = null;
				this.drawingWallStartPoint = null;
				this.drawingWallEndPoint = null;
				this.drawingWallAttr = null;
			});
		} else {
			this._hass.callWS({
				type: 'ecovacs/edit_wall',
				entity_id: this.config.entity,
				wall: this.selectedWallId.substring(3),
				wall_data: wallData,
			}).then(() => {
				// Pre-apply wall change
				this.walls.forEach(element => {
					if (element['id'] == this.selectedWallId) {
						element['points'] = this.drawingWallAttr;
					}
				});

				this.wallMode = "edit";
				this.selectedWallId = null;
				this.drawingWallStartPoint = null;
				this.drawingWallEndPoint = null;
				this.drawingWallAttr = null;
			});
		}
	}


	removeWall() {
		this._hass.callWS({
			type: 'ecovacs/remove_wall',
			entity_id: this.config.entity,
			wall: this.selectedWallId.substring(3)
		}).then(() => {
			for (let index = 0; index < this.walls.length; index++) {
				if (this.walls[index]['id'] == this.selectedWallId) {
					this.walls.splice(index);
				}
			}

			this.wallMode = "edit";
			this.selectedWallId = null;
			this.drawingWallStartPoint = null;
			this.drawingWallEndPoint = null;
			this.drawingWallAttr = null;
		});
	}
	
	vacuumZonedIncreaseButton() {
		if (this.vacuumZonedCleanupRepeats < 2) {
			this.vacuumZonedCleanupRepeats = this.vacuumZonedCleanupRepeats + 1;
		} else {
			this.vacuumZonedCleanupRepeats = 1;
		}
	}

	vacuumStartButton() {
		if (this.selectedMode == "rooms") {
			const room_ids:Array<number> = [];
			this.selectedRooms.forEach(element => {
				room_ids.push(parseInt(element.substring(3)))
			});

			this._hass.callWS({
				type: 'ecovacs/clean_rooms',
				entity_id: this.config.entity,
				rooms: room_ids
			}).then(() => {
				this.selectedRooms = [];
			});

		} else if (this.selectedMode == "zoned_cleanup" && this.drawingZoneAttr) {
			const xs = Math.round(this.drawingZoneAttr['x']);
			const ys = Math.round(this.drawingZoneAttr['y']);
			const xe = Math.round(this.drawingZoneAttr['x'] + this.drawingZoneAttr['width']);
			const ye = Math.round(this.drawingZoneAttr['y'] + this.drawingZoneAttr['height']);
	
			this._hass.callWS({
				type: 'ecovacs/clean_custom_rect',
				entity_id: this.config.entity,
				rect: [
					xs, ys, xe, ye
				],
				cleanings: this.vacuumZonedCleanupRepeats,
			}).then(() => {
				this.drawingZone = false;
				this.drawingZoneStartPoint = null;
				this.drawingZoneEndPoint = null;
				this.drawingZoneAttr = null;
			});


		}
	}

	copyCoords() {
		const xs = Math.round(this.drawingZoneAttr['x']);
		const ys = Math.round(this.drawingZoneAttr['y']);
		const xe = Math.round(this.drawingZoneAttr['x'] + this.drawingZoneAttr['width']);
		const ye = Math.round(this.drawingZoneAttr['y'] + this.drawingZoneAttr['height']);

		const coords = xs + "," + ys + "," + xe + "," + ye;

		console.log("Coords: " + coords);

		navigator.clipboard.writeText(coords).then(function() {
			alert("Coordinates copied to the clipboard.");
		}, function() {
			alert("Failure when copying coordinates to the clipboard!");
		});
	}

	setMode(e) {
		this.selectedMode = e.detail.value;
		if (this.selectedMode != "rooms") {
			this.selectedRooms = [];
		}
		if (this.selectedMode != "walls") {
			this.wallMode = "edit";
			this.selectedWallId = null;
			this.drawingWallStartPoint = null;
			this.drawingWallEndPoint = null;
			this.drawingWallAttr = null;
		}
		if (this.selectedMode != "zoned_cleanup") {
			this.drawingZone = false;
			this.drawingZoneStartPoint = null;
			this.drawingZoneEndPoint = null;
			this.drawingZoneAttr = null;
		}

	}

	updateDrawingZone() {
		this.drawingZoneAttr = {
			'x': Math.min(this.drawingZoneEndPoint[0], this.drawingZoneStartPoint[0]),
			'y': Math.min(this.drawingZoneEndPoint[1], this.drawingZoneStartPoint[1]),
			'width': Math.max(this.drawingZoneEndPoint[0], this.drawingZoneStartPoint[0]) - Math.min(this.drawingZoneEndPoint[0], this.drawingZoneStartPoint[0]),
			'height': Math.max(this.drawingZoneEndPoint[1], this.drawingZoneStartPoint[1]) - Math.min(this.drawingZoneEndPoint[1], this.drawingZoneStartPoint[1]),
		}
	}

	updateDrawingWall() {
		this.drawingWallAttr = [
			[this.drawingWallStartPoint[0], this.drawingWallStartPoint[1]].join(" "),
			[this.drawingWallStartPoint[0], this.drawingWallEndPoint[1]].join(" "),
			[this.drawingWallEndPoint[0], this.drawingWallEndPoint[1]].join(" "),
			[this.drawingWallEndPoint[0], this.drawingWallStartPoint[1]].join(" "),

		].join(",");
	}

	getRelativeCTM(source, target) {
		return target.getScreenCTM().inverse().multiply(source.getScreenCTM())
	}

	getRelativeMousePosition(element, evt) {
		const svg = this.shadowRoot.getElementById('mapRootSvg');
		if ((svg != this.svg) || !this.pt) {
			this.svg = svg;
			this.pt = svg.createSVGPoint()
		}
		
		var CTM = svg.getScreenCTM();
		if (evt.touches) { 
			evt = evt.touches[0]; 
		}

		this.pt.x = evt.clientX;
		this.pt.y = evt.clientY;
		var cursorpt = this.pt.matrixTransform(svg.getScreenCTM().inverse());
		cursorpt = cursorpt.matrixTransform(this.getRelativeCTM(element, svg).inverse());
		
		return {
			x: cursorpt.x,
			y: cursorpt.y
		};
	}

	handleWheel(evt) {
		if (evt.shiftKey) {
			evt.preventDefault();
			evt.stopPropagation();
			
			const svg = this.shadowRoot.getElementById('mapRootSvg');
			const viewport = this.shadowRoot.getElementById('viewport');

			const coords = this.getRelativeMousePosition(viewport, evt);

			const deltaScale = (evt.deltaY * -0.001) * this.viewportScale;

			const newScale = Math.min(Math.max(this.viewportScale + deltaScale, 1), 4);

			this.viewportOffsetX -= (coords.x * (newScale - this.viewportScale));
			this.viewportOffsetY -= (coords.y * (newScale - this.viewportScale));
			this.viewportScale = newScale;
		}
	}

	preventQuietly(evt) {
		if (evt) {
			if (evt.cancelable && evt.preventDefault) {
				evt.preventDefault();
			}
			if (evt.stopPropagation) {
				evt.stopPropagation()
			}
		}
	}

	startDrag(evt) {
		if (evt.touches && evt.touches.length > 1) {
			// Stop any ongoing drag handling.
			this.endDrag(null);

			// Check if pinching
			if (evt.touches.length == 2) {
				this.pinchingMap = true;

				const x1 = evt.touches[0].clientX;
				const y1 = evt.touches[0].clientY;
				const x2 = evt.touches[1].clientX;
				const y2 = evt.touches[1].clientY;

				this.pinchDistance = Math.hypot(x1 - x2, y1 - y2);
				this.pinchCenter = [(x1 + x2) / 2, (y1 + y2) / 2];
			}
		} else {

			// Start dragging a draggable element.
			if (evt.target.classList.contains('draggable')) {
				this.selectedElementId = evt.target.id;
				this.moveOffset = this.getRelativeMousePosition(evt.target, evt);

			// Start drawing a zone to clean
			} else if (this.selectedMode == "zoned_cleanup" && !this.drawingZoneAttr) {
				const customRectContainer = this.shadowRoot.getElementById('customRectContainer');
				if (customRectContainer) {
					this.drawingZone = true;

					const coords = this.getRelativeMousePosition(customRectContainer, evt);

					this.drawingZoneStartPoint = [coords.x, coords.y];
					this.drawingZoneEndPoint = [coords.x, coords.y];

					this.updateDrawingZone();
				}

			// Start drawing new wall
			} else if (this.selectedMode == "walls" && this.wallMode == "add" && !this.drawingWallAttr) {
				const customRectContainer = this.shadowRoot.getElementById('polygonContainer');
				if (customRectContainer) {
					this.drawingNewWall = true;

					const coords = this.getRelativeMousePosition(customRectContainer, evt);

					this.selectedWallId = "newWall";

					this.drawingWallStartPoint = [coords.x, coords.y];
					this.drawingWallEndPoint = [coords.x, coords.y];

					this.updateDrawingWall();
				}

			// Moving map
			} else {
				const viewport = this.shadowRoot.getElementById('mapRootSvg');

				this.movingMap = true;
				this.moveOffset = this.getRelativeMousePosition(viewport, evt);
			}
		}
	}
	
	drag(evt) {
		// Dragging a draggable element
		if (this.selectedElementId) {
			this.preventQuietly(evt);

			const selectedElement = this.shadowRoot.getElementById(this.selectedElementId);

			const coords = this.getRelativeMousePosition(selectedElement, evt);

			const diffX = this.moveOffset.x - coords.x;
			const diffy = this.moveOffset.y - coords.y;

			// TODO: Generalize handling
			if (selectedElement.id.startsWith("drawingZone")) {
				if (selectedElement.id == "drawingZone_ss") {
					this.drawingZoneStartPoint[0] -= diffX;
					this.drawingZoneStartPoint[1] -= diffy;

				} else if (selectedElement.id == "drawingZone_se") {
					this.drawingZoneStartPoint[0] -= diffX;
					this.drawingZoneEndPoint[1] -= diffy;

				} else if (selectedElement.id == "drawingZone_ee") {
					this.drawingZoneEndPoint[0] -= diffX;
					this.drawingZoneEndPoint[1] -= diffy;
			
				} else if (selectedElement.id == "drawingZone_es") {
					this.drawingZoneEndPoint[0] -= diffX;
					this.drawingZoneStartPoint[1] -= diffy;

				} else {
					this.drawingZoneStartPoint[0] -= diffX;
					this.drawingZoneStartPoint[1] -= diffy;
					this.drawingZoneEndPoint[0] -= diffX;
					this.drawingZoneEndPoint[1] -= diffy;
				}

				this.updateDrawingZone();

			} else if (selectedElement.id.startsWith("vw") || (selectedElement.id == "newWall")) {
				if (selectedElement.id == "vw_ss") {
					this.drawingWallStartPoint[0] -= diffX;
					this.drawingWallStartPoint[1] -= diffy;

				} else if (selectedElement.id == "vw_se") {
					this.drawingWallStartPoint[0] -= diffX;
					this.drawingWallEndPoint[1] -= diffy;

				} else if (selectedElement.id == "vw_ee") {
					this.drawingWallEndPoint[0] -= diffX;
					this.drawingWallEndPoint[1] -= diffy;
			
				} else if (selectedElement.id == "vw_es") {
					this.drawingWallEndPoint[0] -= diffX;
					this.drawingWallStartPoint[1] -= diffy;

				} else {
					this.drawingWallStartPoint[0] -= diffX;
					this.drawingWallStartPoint[1] -= diffy;
					this.drawingWallEndPoint[0] -= diffX;
					this.drawingWallEndPoint[1] -= diffy;
				}

				this.updateDrawingWall();
			}

			this.moveOffset = coords;
		
		// Drawing a zone
		} else if (this.drawingZone) {
			this.preventQuietly(evt);

			const customRectContainer = this.shadowRoot.getElementById('customRectContainer');

			const coords = this.getRelativeMousePosition(customRectContainer, evt);

			this.drawingZoneEndPoint = [coords.x, coords.y];

			this.updateDrawingZone();
	
		// Drawing a wall
		} else if (this.drawingNewWall) {
			this.preventQuietly(evt);

			const customRectContainer = this.shadowRoot.getElementById('polygonContainer');

			const coords = this.getRelativeMousePosition(customRectContainer, evt);

			this.drawingWallEndPoint = [coords.x, coords.y];

			this.updateDrawingWall();
		
		// Moving map.
		} else if (this.movingMap) {
			this.preventQuietly(evt);

			const viewport = this.shadowRoot.getElementById('mapRootSvg');

			const coords = this.getRelativeMousePosition(viewport, evt);

			const diffX = this.moveOffset.x - coords.x;
			const diffy = this.moveOffset.y - coords.y;
			
			this.viewportOffsetX -= diffX;
			this.viewportOffsetY -= diffy;

			this.moveOffset = this.getRelativeMousePosition(viewport, evt);

		// Pinching map (zoom)
		} else if (this.pinchingMap) {
			this.preventQuietly(evt);

			const x1 = evt.touches[0].clientX;
			const y1 = evt.touches[0].clientY;
			const x2 = evt.touches[1].clientX;
			const y2 = evt.touches[1].clientY;

			const newPinchDistance = Math.hypot(x1 - x2, y1 - y2);
			
			const viewport = this.shadowRoot.getElementById('viewport');


			const coords = this.getRelativeMousePosition(viewport, {
				/* updated version:
				 * clientX: (x1 + x2) / 2,
				 * clientY: (y1 + y2) / 2,
				*/
				clientX: this.pinchCenter[0],
				clientY: this.pinchCenter[1],
			});

			const deltaScale = ((this.pinchDistance - newPinchDistance) * -0.01) * this.viewportScale;

			const newScale = Math.min(Math.max(this.viewportScale + deltaScale, 1), 4);

			this.viewportOffsetX -= (coords.x * (newScale - this.viewportScale));
			this.viewportOffsetY -= (coords.y * (newScale - this.viewportScale));
			this.viewportScale = newScale;

			this.pinchDistance = newPinchDistance;
		}
	}

	endDrag(evt) {
		if (this.selectedElementId) {
			this.selectedElementId = null;
			this.moveOffset = null;
			this.transform = null;

		} else if (this.drawingZone) {
			this.drawingZone = false;

		} else if (this.drawingNewWall) {
			this.drawingNewWall = false;

		} else if (this.movingMap) {
			this.movingMap = false;

		} else if (evt && this.pinchingMap && evt.touches && evt.touches.length < 2) {
			this.pinchingMap = false;

			if (evt.touches.length == 1) {
				this.startDrag(evt.touches[0]);
			}
		}
	}

	render() {
		if (!this._hass || !this.config 
				|| !this.map_info_timestamp
				|| !this.map_background_left 
				|| !this.map_background_top 
				|| !this.map_background_right 
				|| !this.map_background_bottom) {
			return html``;
		}
		
		return html`
			<ha-card id="ecovacsMap" header="Map">
				<div class="card-content">
					<div id="mapWrapper">
						${svg`
							<svg id="mapRootSvg" xmlns="http://www.w3.org/2000/svg" class="map" viewBox="${this.map_background_left} ${this.map_background_top} ${this.map_background_right - this.map_background_left} ${this.map_background_bottom - this.map_background_top}"
									@wheel="${this.handleWheel}"
									@mousedown="${this.startDrag}" @touchstart="${this.startDrag}"
									@mousemove="${this.drag}" @touchmove="${this.drag}"
									@mouseup="${this.endDrag}" @touchend="${this.endDrag}"
									@mouseleave="${this.endDrag}" @touchleave="${this.endDrag}" @touchcancel="${this.endDrag}"
								<defs>
									<radialGradient id="device_bg" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
										<stop offset="70%" style="stop-color:#0000FF;" />
										<stop offset="97%" style="stop-color:#0000FF00;" />
									</radialGradient>
								</defs>
								<g id="viewport" transform="translate(${this.viewportOffsetX},${this.viewportOffsetY}) scale(${this.viewportScale},${this.viewportScale})">
									<image x="${this.map_background_left}" y="${this.map_background_top}" class="map_bg no_pointer_event" href="data:image/png;base64,${this.map_background_base64}" width="${this.map_background_right - this.map_background_left}" height="${this.map_background_bottom - this.map_background_top}" />

									<g id="polygonContainer" transform="translate(${this.map_width / 2}, ${this.map_height / 2}) scale(1, -1) scale(${this.coordination_scale}, ${this.coordination_scale})">
										${(this.selectedMode == "rooms") ? svg`
											${this.rooms.map((i, idx) => svg`
												<polygon id="${i.id}" points="${i.points}" class="${(this.selectedRooms.indexOf(i.id) != -1) ? 'room_sa_selected' : 'room_sa'} room_sa_${idx % 5}" @click="${this.handleRoomClick}"/>
											`)}
										` : ""}

										${this.walls.map(i => svg`
											${(this.selectedWallId != i.id) ? svg`
												<polygon id="${i.id}" points="${i.points}" class="room_vw ${this.selectedMode != "walls" || this.wallMode == "add" ? "no_pointer_event" : ""}" @click="${this.handleWallClick}"/>
											` : null}
										`)}
									</g>

									<!-- Path -->
									<g transform="translate(${this.map_width / 2}, ${this.map_height / 2})  rotate(90) scale(-1, -1) scale(${this.coordination_scale * 10}, ${this.coordination_scale * 10})">
										<!-- Last cleaning path (dynamically updated) -->
										<path id="path" class="path" d="${this.path_points}" stroke="white" fill="none"/>
									</g>

									<!-- Vacuum -->
									<g transform="translate(${this.map_width / 2}, ${this.map_height / 2}) scale(1, -1) scale(${this.coordination_scale}, ${this.coordination_scale})">
										<circle class="device no_pointer_event" cx="${this.device_pos.x}" cy="${this.device_pos.y}" r="${(4 / this.coordination_scale)}" fill="url(#device_bg)" />
										<circle class="device no_pointer_event" cx="${this.device_pos.x}" cy="${this.device_pos.y}" r="${((4 * 0.68) / this.coordination_scale)}" stroke="white" fill="blue" stroke-width="${(0.5 / this.coordination_scale)}"/>

										<!-- Charging station -->
										<circle class="no_pointer_event" cx="${this.charger_pos.x}" cy="${this.charger_pos.y}" r="${(2 / this.coordination_scale)}" stroke="green" fill="green" stroke-width="${(0.5 / this.coordination_scale)}" />
									</g>

									<!-- wall drawing -->
									<g id="polygonContainer" transform="translate(${this.map_width / 2}, ${this.map_height / 2}) scale(1, -1) scale(${this.coordination_scale}, ${this.coordination_scale})">
										${this.walls.map(i => svg`
											${(this.selectedWallId == i.id) ? svg`
												<polygon id="${i.id}" points="${this.drawingWallAttr}" class="room_vw draggable" @click="${this.handleWallClick}" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}"/>
											` : null}
										`)}
										${(this.selectedWallId == "newWall") ? svg`
											<polygon id="newWall" points="${this.drawingWallAttr}" class="room_vw draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}"/>
										` : null}
										${(this.drawingWallStartPoint && this.drawingWallEndPoint) ? svg`
											<circle id="vw_ss" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingWallStartPoint[0]}" cy="${this.drawingWallStartPoint[1]}" r="200" fill="red"/>
											<circle id="vw_se" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingWallStartPoint[0]}" cy="${this.drawingWallEndPoint[1]}" r="200" fill="red"/>
											<circle id="vw_ee" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingWallEndPoint[0]}" cy="${this.drawingWallEndPoint[1]}" r="200" fill="red"/>
											<circle id="vw_es" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingWallEndPoint[0]}" cy="${this.drawingWallStartPoint[1]}" r="200" fill="red"/>										
										` : null}
									</g>

									<!-- area clean drawing -->
									<g id="customRectContainer" transform="translate(${this.map_width / 2}, ${this.map_height / 2}) scale(1, -1) scale(${this.coordination_scale}, ${this.coordination_scale})">
										${(this.drawingZoneAttr != null) ? svg`
											<rect x="${this.drawingZoneAttr.x}" y="${this.drawingZoneAttr.y}" width="${this.drawingZoneAttr.width}" height="${this.drawingZoneAttr.height}" 
												id="drawingZone"
												class="draggable"
												fill="green"
												fill-opacity="0.2"
												stroke="green"
												stroke-width="1.5"
												stroke-dasharray="4.5,4.5"
												style="vector-effect: non-scaling-stroke;"
												@mousedown="${this.startDrag}" @touchstart="${this.startDrag}"/>

											<circle id="drawingZone_ss" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingZoneStartPoint[0]}" cy="${this.drawingZoneStartPoint[1]}" r="200" fill="green"/>
											<circle id="drawingZone_se" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingZoneStartPoint[0]}" cy="${this.drawingZoneEndPoint[1]}" r="200" fill="green"/>
											<circle id="drawingZone_ee" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingZoneEndPoint[0]}" cy="${this.drawingZoneEndPoint[1]}" r="200" fill="green"/>
											<circle id="drawingZone_es" class="draggable" @mousedown="${this.startDrag}" @touchstart="${this.startDrag}" cx="${this.drawingZoneEndPoint[0]}" cy="${this.drawingZoneStartPoint[1]}" r="200" fill="green"/>
										` : null}
									</g>
								</g>
							</svg>
						`}
						<div id="mapControl">
							<mwc-fab icon="crosshairs-gps"></mwc-fab>
							<mwc-fab icon="magnify-plus-outline"></mwc-fab>
							<mwc-fab icon="magnify-minus-outline"></mwc-fab>
						</div>
					</div>
					<div class="controls">
						<div>
							<ha-paper-dropdown-menu label="Modalità" style="width: 100%">
								<paper-listbox slot="dropdown-content" 
										attr-for-selected="value" 
										.selected="${this.selectedMode}"
										@selected-changed=${this.setMode}>
									${Array.from(this.modes.keys()).map(i => html`
										<paper-item style="white-space: nowrap" value=${i}>${this.modes.get(i)}</pre></paper-item>
									`)}
								</paper-listbox>
							</ha-paper-dropdown-menu>
						</div>
						<div style="display: flex; justify-content: space-between;">
							<span id="increaseButton" ?hidden="${!(this.selectedMode == 'zoned_cleanup')}">
								<mwc-button @click="${() => this.vacuumZonedIncreaseButton()}">Ripetizioni ${this.vacuumZonedCleanupRepeats}</mwc-button>
							</span>
							<span ?hidden="${!(this.selectedMode != 'walls')}">
								<mwc-button @click="${() => this.vacuumStartButton()}">Avvia</mwc-button>
								<span ?hidden="${!(this.selectedMode == 'zoned_cleanup')}">
									<mwc-button @click="${() => this.copyCoords()}">Copia coordinate</mwc-button>
								</span>
							</span>

							<span ?hidden="${!(this.selectedMode == 'walls' && !this.selectedWallId && this.wallMode != "add")}">
								<mwc-button @click="${() => this.addWall()}">Aggiungi</mwc-button> 
							</span>
							<span ?hidden="${!(this.selectedMode == 'walls' && this.selectedWallId && this.wallMode == "edit")}">
								<mwc-button @click="${() => this.removeWall()}">Elimina</mwc-button>
							</span>
							<span ?hidden="${!(this.selectedMode == 'walls' && (this.selectedWallId || this.wallMode == "add"))}">
								<mwc-button @click="${() => this.cancelWallChange()}">Annulla</mwc-button>
							</span>
							<span ?hidden="${!(this.selectedMode == 'walls' && this.selectedWallId)}">
								<mwc-button @click="${() => this.confirmWallChange()}">Applica</mwc-button>
							</spen> 
						</div>
					</div>
				</div>
			</ha-card>
		`;
	}

	static get styles() {
		return css`
			:host,
			ha-card,
			paper-dropdown-menu {
				display: block;
			}

			paper-item {
				width: 450px;
			}

			.mapWrapper {
				position: relative;
			}

			.mapControl {
				position: absolute;
				right: 12px;
				bottom: 12px;
			}

			.map {
				margin: 6px;
				width: 100%;
				height: auto;
			}

			.map_bg {
				image-rendering: pixelated;
			}

			.no_pointer_event {
				pointer-events: none;
			}

			.path {
				pointer-events: none;
				stroke-width: 1.5;
				stroke-linejoin: round;
				vector-effect: non-scaling-stroke;
			}

			.room_vw {
				fill: red;
				fill-opacity: 0.2;
				stroke: red;
				stroke-width: 1.5;
				stroke-dasharray: 4.5, 4.5;
				vector-effect: non-scaling-stroke;
			}

			.room_sa {
				stroke: none;
				fill-opacity: 0.2;
			}

			.room_sa:hover {
				fill-opacity: 0.4;
			}

			.room_sa_selected  {
				stroke: green;
				stroke-width: 2;
				vector-effect: non-scaling-stroke;
				fill-opacity: 0.6;
			}

			.room_sa_selected:hover  {
				fill-opacity: 8;
			}

			.room_sa_0 {
				fill: violet;
			}
			.room_sa_1 {
				fill: green;
			}
			.room_sa_2 {
				fill: magenta;
			}
			.room_sa_3 {
				fill: purple;
			}
			.room_sa_4 {
				fill: maroon;
			}

			.device {
				-webkit-transition: all 0.7s ease-in-out;
				-moz-transition: all 0.7s ease-in-out;
				transition: all 0.5s ease-in-out;
			}
		`;
	  }	
}



console.info("%c ECOVACS-CARD %c ".concat("1.0.0", " "), "color: white; background: coral; font-weight: 700;", "color: coral; background: white; font-weight: 700;");
