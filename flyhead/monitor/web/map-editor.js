import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

// Offline editor: only local map assets are fetched. No robot/control connection exists.
const $ = id => document.getElementById(id);
const SCHEMA = 'xingtian.map-correction-draft';
const MAX_REGIONS = 64;
const MAX_VERTICES = 128;
const HISTORY_LIMIT = 50;
const state = {
    metadata: null,
    identity: null,
    storageKey: null,
    positions: null,
    baseColors: null,
    regions: [],
    selectedId: null,
    vertices: [],
    drawing: false,
    busy: false,
    revision: 0,
    mask: null,
    counts: new Map(),
    unionCount: 0,
    displayMin: 0,
    displayMax: 1,
    undo: [],
    redo: [],
    createdAt: new Date().toISOString(),
};
let renderer, camera, controls, scene, pointGeometry, pointMaterial, outlines;
let viewMode = 'top';
let pointerDown = null;
const ray = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const heightClipPlanes = [
    new THREE.Plane(new THREE.Vector3(0, 0, 1), 0),
    new THREE.Plane(new THREE.Vector3(0, 0, -1), 1),
];

// Same banded height contour as the console (blue low -> red high); magenta, outside the
// contour palette, marks candidate points.
const BANDS = ['#0000ff', '#0055ff', '#00aaff', '#00ffff', '#00ff80', '#55ff00', '#ffff00', '#ffaa00', '#ff0000']
    .map(h => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255]);
function heightColor(z, out, o) {
    const k = Math.max(0, Math.min(BANDS.length - 1, Math.floor((z + 0.4) / 2.6 * BANDS.length)));
    out[o] = BANDS[k][0]; out[o + 1] = BANDS[k][1]; out[o + 2] = BANDS[k][2];
}

function ask(title, text) {
    const dialog = $('ask');
    $('askTitle').textContent = title;
    $('askBody').textContent = text;
    return new Promise(resolve => {
        const done = ok => { dialog.close(); $('askYes').onclick = $('askNo').onclick = dialog.oncancel = null; resolve(ok); };
        $('askYes').onclick = () => done(true);
        $('askNo').onclick = () => done(false);
        dialog.oncancel = event => { event.preventDefault(); done(false); };
        dialog.showModal();
        $('askNo').focus();
    });
}

function message(text, error = false) {
    $('message').textContent = text;
    $('message').classList.toggle('error', error);
}

function displayHeightBounds() {
    const low = Math.floor(state.metadata.bounds_min[2] * 100) / 100;
    const high = Math.max(low + 0.01, Math.ceil(state.metadata.bounds_max[2] * 100) / 100);
    return [low, high];
}

function setDisplayHeight(low, high) {
    state.displayMin = low;
    state.displayMax = high;
    heightClipPlanes[0].constant = -low;
    heightClipPlanes[1].constant = high;
    $('displayMin').value = $('displayMinRange').value = low.toFixed(2);
    $('displayMax').value = $('displayMaxRange').value = high.toFixed(2);
    $('heightInfo').textContent = `Showing Z ${low.toFixed(2)}–${high.toFixed(2)} m only (absolute map height).`;
}

function bindDisplayHeight() {
    const [minimum, maximum] = displayHeightBounds();
    for (const id of ['displayMin', 'displayMinRange', 'displayMax', 'displayMaxRange']) {
        const input = $(id);
        input.min = minimum.toFixed(2);
        input.max = maximum.toFixed(2);
        const updateHeight = () => {
            if (!input.value.trim() || !Number.isFinite(Number(input.value))) return;
            const value = Math.round(Math.max(minimum, Math.min(maximum, Number(input.value))) * 100) / 100;
            if (id.startsWith('displayMin')) {
                setDisplayHeight(Math.min(value, state.displayMax - 0.01), state.displayMax);
            } else {
                setDisplayHeight(state.displayMin, Math.max(value, state.displayMin + 0.01));
            }
        };
        // Sliders update immediately; number fields keep partial typed values until committed.
        if (input.type === 'range') input.oninput = updateHeight;
        input.onchange = () => {
            updateHeight();
            setDisplayHeight(state.displayMin, state.displayMax);
        };
    }
    $('resetDisplayHeight').onclick = () => setDisplayHeight(minimum, maximum);
    $('useDisplayHeight').onclick = () => {
        $('zMin').value = state.displayMin.toFixed(2);
        $('zMax').value = state.displayMax.toFixed(2);
        const region = selectedRegion();
        if (region && !state.drawing) {
            changeDraft(() => {
                region.zMin = state.displayMin;
                region.zMax = state.displayMax;
            });
            message('The selected region now uses the display height range (undoable). The map is unchanged.');
        } else {
            redrawOutlines();
            message('The polygon being drawn uses the display height range; only points inside it become candidates.');
        }
    };
    setDisplayHeight(minimum, maximum);
}

function snapshot() {
    return JSON.parse(JSON.stringify({regions: state.regions, selectedId: state.selectedId}));
}

function selectedRegion() {
    return state.regions.find(region => region.id === state.selectedId);
}

function polygonArea(vertices) {
    let sum = 0;
    for (let i = 0; i < vertices.length; i++) {
        const a = vertices[i];
        const b = vertices[(i + 1) % vertices.length];
        sum += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(sum) / 2;
}

function cross(a, b, c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function onSegment(a, b, p) {
    return Math.abs(cross(a, b, p)) < 1e-8
        && p[0] >= Math.min(a[0], b[0]) - 1e-8
        && p[0] <= Math.max(a[0], b[0]) + 1e-8
        && p[1] >= Math.min(a[1], b[1]) - 1e-8
        && p[1] <= Math.max(a[1], b[1]) + 1e-8;
}

function segmentsIntersect(a, b, c, d) {
    const abC = cross(a, b, c);
    const abD = cross(a, b, d);
    const cdA = cross(c, d, a);
    const cdB = cross(c, d, b);
    return (abC * abD < 0 && cdA * cdB < 0)
        || onSegment(a, b, c) || onSegment(a, b, d)
        || onSegment(c, d, a) || onSegment(c, d, b);
}

function validatePolygon(vertices) {
    if (!Array.isArray(vertices) || vertices.length < 3 || vertices.length > MAX_VERTICES) {
        throw new Error(`Every polygon needs 3–${MAX_VERTICES} vertices.`);
    }
    const low = state.metadata.bounds_min;
    const high = state.metadata.bounds_max;
    for (const vertex of vertices) {
        if (!Array.isArray(vertex) || vertex.length !== 2 || !vertex.every(Number.isFinite)) {
            throw new Error('Vertices must be finite map coordinates [x, y].');
        }
        if (vertex[0] < low[0] || vertex[0] > high[0] || vertex[1] < low[1] || vertex[1] > high[1]) {
            throw new Error('Vertices must stay inside the display map bounds.');
        }
    }
    for (let i = 0; i < vertices.length; i++) {
        const next = (i + 1) % vertices.length;
        if (Math.hypot(vertices[i][0] - vertices[next][0], vertices[i][1] - vertices[next][1]) < 1e-6) {
            throw new Error('Repeated adjacent vertex; undo it and pick again.');
        }
        for (let j = i + 1; j < vertices.length; j++) {
            if (j === next || (j + 1) % vertices.length === i) continue;
            if (segmentsIntersect(vertices[i], vertices[next], vertices[j], vertices[(j + 1) % vertices.length])) {
                throw new Error('The polygon intersects itself or repeats an edge; undo the crossing vertex.');
            }
        }
    }
    if (polygonArea(vertices) < 1e-6) throw new Error('The polygon has zero area; pick non-collinear vertices.');
}

function insidePolygon(x, y, vertices) {
    let inside = false;
    for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
        const a = vertices[i];
        const b = vertices[j];
        if (onSegment(a, b, [x, y])) return true;
        if ((a[1] > y) !== (b[1] > y)
            && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) {
            inside = !inside;
        }
    }
    return inside;
}

function readHeightRange() {
    if (!$('zMin').value.trim() || !$('zMax').value.trim()) throw new Error('Enter both Min Z and Max Z.');
    const low = Number($('zMin').value);
    const high = Number($('zMax').value);
    if (![low, high].every(Number.isFinite) || low >= high || Math.max(Math.abs(low), Math.abs(high)) > 10000) {
        throw new Error('Heights must be finite numbers with Min Z below Max Z.');
    }
    return [low, high];
}

function draftDocument() {
    return {
        schema: SCHEMA,
        version: 1,
        status: 'draft_unverified',
        apply_to_robot: false,
        created_at: state.createdAt,
        exported_at: new Date().toISOString(),
        map_identity: state.identity,
        units: 'metres',
        height_reference: 'absolute_map_z',
        evidence_status: 'not_collected',
        display_voxel_m: state.metadata.display_voxel_m,
        candidate_display_points: state.busy ? null : state.unionCount,
        regions: state.regions.map(region => ({
            id: region.id,
            name: region.name,
            operation: 'propose_clear_static_obstacle',
            polygon_xy_m: region.vertices.map(vertex => [...vertex]),
            z_min_m: region.zMin,
            z_max_m: region.zMax,
            area_xy_m2: polygonArea(region.vertices),
            candidate_display_points: state.busy ? null : (state.counts.get(region.id) ?? null),
        })),
    };
}

function persistDraft() {
    try {
        localStorage.setItem(state.storageKey, JSON.stringify(draftDocument()));
        $('storageInfo').textContent = 'Saved in this browser (finished regions only; no map file is written). Export JSON to keep it elsewhere.';
    } catch (error) {
        $('storageInfo').textContent = 'Browser storage is unavailable or full; the draft only exists in this page. Export JSON to keep it: ' + error.message;
    }
}

function validateDraft(document) {
    if (!document || document.schema !== SCHEMA || document.version !== 1
        || document.status !== 'draft_unverified' || document.apply_to_robot !== false
        || document.units !== 'metres' || document.height_reference !== 'absolute_map_z'
        || document.evidence_status !== 'not_collected') {
        throw new Error('Only unapplied, unverified drafts from this editor are supported.');
    }
    for (const key of Object.keys(state.identity)) {
        if (document.map_identity?.[key] !== state.identity[key]) {
            throw new Error('The draft belongs to a different map identity or frame; not imported.');
        }
    }
    if (!Array.isArray(document.regions) || document.regions.length > MAX_REGIONS) {
        throw new Error(`A draft holds at most ${MAX_REGIONS} regions.`);
    }
    const ids = new Set();
    return document.regions.map(region => {
        if (!region || typeof region.id !== 'string' || !region.id || region.id.length > 100 || ids.has(region.id)) {
            throw new Error('Region id missing, duplicated or too long.');
        }
        ids.add(region.id);
        if (typeof region.name !== 'string' || region.name.length > 80
            || region.operation !== 'propose_clear_static_obstacle') {
            throw new Error('Invalid region name or operation.');
        }
        validatePolygon(region.polygon_xy_m);
        if (![region.z_min_m, region.z_max_m].every(Number.isFinite)
            || region.z_min_m >= region.z_max_m
            || Math.max(Math.abs(region.z_min_m), Math.abs(region.z_max_m)) > 10000) {
            throw new Error('Invalid height range in the draft.');
        }
        return {
            id: region.id,
            name: region.name,
            vertices: region.polygon_xy_m.map(vertex => [...vertex]),
            zMin: region.z_min_m,
            zMax: region.z_max_m,
        };
    });
}

function changeDraft(change) {
    state.undo.push(snapshot());
    if (state.undo.length > HISTORY_LIMIT) state.undo.shift();
    state.redo = [];
    change();
    refreshDraft();
}

function refreshDraft() {
    renderRegions();
    redrawOutlines();
    updateCandidates().catch(error => {
        state.busy = false;
        message('Candidate preview failed: ' + error.message, true);
        updateButtons();
    });
    persistDraft();
}

function updateButtons() {
    const ready = !!state.positions;
    $('draw').disabled = !ready || state.drawing || state.regions.length >= MAX_REGIONS;
    $('finish').disabled = !state.drawing || state.vertices.length < 3;
    $('undoVertex').disabled = !state.drawing || !state.vertices.length;
    $('cancelDraw').disabled = !state.drawing;
    $('updateRegion').disabled = !selectedRegion() || state.drawing;
    $('deleteRegion').disabled = !selectedRegion() || state.drawing;
    $('undo').disabled = !state.undo.length || state.drawing;
    $('redo').disabled = !state.redo.length || state.drawing;
    $('spatialView').disabled = !ready || state.drawing;
    $('topView').disabled = !ready;
    $('fitView').disabled = !ready;
    $('hideCandidates').disabled = !ready || state.busy;
    $('exportDraft').disabled = !ready || state.busy || state.drawing || !state.regions.length;
    $('importDraft').disabled = !ready || state.drawing;
    $('clearDraft').disabled = !ready || state.drawing || !state.regions.length;
    for (const id of ['regionName', 'zMin', 'zMax', 'pointSize',
        'displayMin', 'displayMinRange', 'displayMax', 'displayMaxRange',
        'resetDisplayHeight', 'useDisplayHeight']) $(id).disabled = !ready;
    $('viewport').classList.toggle('drawing', state.drawing);
    controls.mouseButtons.LEFT = state.drawing ? null : THREE.MOUSE.PAN;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.enableRotate = viewMode === 'spatial' && !state.drawing;
    if (controls.enableRotate) controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
}

function renderRegions() {
    $('regionList').replaceChildren();
    if (!state.regions.length) $('regionList').textContent = 'No finished regions yet.';
    for (const region of state.regions) {
        const button = document.createElement('button');
        button.type = 'button';
        button.classList.toggle('selected', region.id === state.selectedId);
        button.disabled = state.drawing;
        button.textContent = `${region.name || 'Unnamed region'} · ${polygonArea(region.vertices).toFixed(2)} m² · Z ${region.zMin.toFixed(2)}–${region.zMax.toFixed(2)} m`;
        button.onclick = () => {
            state.selectedId = region.id;
            $('regionName').value = region.name;
            $('zMin').value = region.zMin;
            $('zMax').value = region.zMax;
            renderRegions();
            redrawOutlines();
            renderCounts();
        };
        $('regionList').append(button);
    }
    updateButtons();
}

function renderCounts() {
    const current = selectedRegion();
    $('selectionInfo').textContent = state.busy ? 'Computing candidate points…'
        : `All regions: ${state.unionCount.toLocaleString()} / ${state.metadata.points.toLocaleString()} display points (overlaps counted once)`
        + (current ? `\nSelected region: ${(state.counts.get(current.id) || 0).toLocaleString()} display points` : '')
        + '\nCounted with each region\'s saved heights, independent of the display slice; these are not source map points, obstacle cells or free-space evidence.';
}

function addOutline(vertices, z, color, closed) {
    if (!vertices.length) return;
    const points = vertices.map(vertex => new THREE.Vector3(vertex[0], vertex[1], z));
    if (closed) points.push(points[0].clone());
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({color, depthTest: false}));
    line.renderOrder = 2;
    outlines.add(line);
    if (!closed) {
        const dots = new THREE.Points(geometry.clone(), new THREE.PointsMaterial({color, size: 7, sizeAttenuation: false, depthTest: false}));
        dots.renderOrder = 3;
        outlines.add(dots);
    }
}

function redrawOutlines() {
    for (const child of [...outlines.children]) {
        outlines.remove(child);
        child.geometry.dispose();
        child.material.dispose();
    }
    for (const region of state.regions) {
        const color = region.id === state.selectedId ? 0xffb71b : 0xd9001b;
        addOutline(region.vertices, region.zMax, color, true);
        if (viewMode === 'spatial') addOutline(region.vertices, region.zMin, color, true);
    }
    addOutline(state.vertices, Number($('zMax').value) || 0, 0x000000, false);
    $('draftInfo').textContent = state.drawing ? `Drawing: ${state.vertices.length}/${MAX_VERTICES} vertices`
        : `${state.regions.length} candidate region(s) finished; the map is unchanged.`;
    $('vertices').replaceChildren();
    for (const [index, vertex] of state.vertices.entries()) {
        const item = document.createElement('li');
        item.textContent = `${index + 1}: X ${vertex[0].toFixed(3)}, Y ${vertex[1].toFixed(3)} m`;
        $('vertices').append(item);
    }
    updateButtons();
}

async function updateCandidates() {
    const revision = ++state.revision;
    state.busy = true;
    updateButtons();
    renderCounts();
    const regions = state.regions.map(region => ({
        ...region,
        minX: Math.min(...region.vertices.map(vertex => vertex[0])),
        maxX: Math.max(...region.vertices.map(vertex => vertex[0])),
        minY: Math.min(...region.vertices.map(vertex => vertex[1])),
        maxY: Math.max(...region.vertices.map(vertex => vertex[1])),
    }));
    const mask = new Uint8Array(state.metadata.points);
    const counts = new Map(regions.map(region => [region.id, 0]));
    let unionCount = 0;
    for (let start = 0; start < mask.length; start += 6000) {
        if (revision !== state.revision) return;
        const end = Math.min(mask.length, start + 6000);
        for (let i = start; i < end; i++) {
            const x = state.positions[i * 3];
            const y = state.positions[i * 3 + 1];
            const z = state.positions[i * 3 + 2];
            for (const region of regions) {
                if (z < region.zMin || z > region.zMax || x < region.minX || x > region.maxX || y < region.minY || y > region.maxY) continue;
                if (insidePolygon(x, y, region.vertices)) {
                    counts.set(region.id, counts.get(region.id) + 1);
                    if (!mask[i]) {
                        mask[i] = 1;
                        unionCount++;
                    }
                }
            }
        }
        await new Promise(resolve => setTimeout(resolve, 0));
    }
    if (revision !== state.revision) return;
    state.mask = mask;
    state.counts = counts;
    state.unionCount = unionCount;
    state.busy = false;
    applyPreview();
    renderCounts();
    updateButtons();
    persistDraft();
}

function applyPreview() {
    const colors = pointGeometry.attributes.color.array;
    colors.set(state.baseColors);
    const hidden = $('hideCandidates').checked;
    if (hidden && state.mask) {
        const indices = new Uint32Array(state.metadata.points - state.unionCount);
        let kept = 0;
        for (let i = 0; i < state.mask.length; i++) {
            if (!state.mask[i]) indices[kept++] = i;
        }
        pointGeometry.setIndex(new THREE.BufferAttribute(indices, 1));
    } else {
        pointGeometry.setIndex(null);
        if (state.mask) {
            for (let i = 0; i < state.mask.length; i++) {
                if (state.mask[i]) colors.set([0.85, 0.0, 0.85], i * 3);
            }
        }
    }
    pointGeometry.attributes.color.needsUpdate = true;
}

function setView(mode, fit = false) {
    viewMode = mode;
    const low = state.metadata.bounds_min;
    const high = state.metadata.bounds_max;
    const target = fit ? new THREE.Vector3((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]) : controls.target.clone();
    const distance = Math.max(high[0] - low[0], high[1] - low[1], 5);
    controls.enableDamping = false;
    controls.update();
    controls.target.copy(target);
    // Keep a fixed Z-up frame: OrbitControls caches its up-axis transform.
    if (mode === 'top') camera.position.set(target.x, target.y - 0.00001, target.z + distance * 2);
    else camera.position.set(target.x + distance, target.y - distance, target.z + distance);
    if (fit) {
        const aspect = $('viewport').clientWidth / $('viewport').clientHeight;
        const visibleHeight = Math.max(high[1] - low[1], (high[0] - low[0]) / aspect, 5) * 1.15;
        camera.zoom = 40 / visibleHeight;
    }
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    controls.update();
    redrawOutlines();
}

function mapPosition(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -state.metadata.bounds_min[2]);
    return ray.ray.intersectPlane(plane, new THREE.Vector3());
}

function finishPolygon() {
    if (!state.drawing) return;
    try {
        validatePolygon(state.vertices);
        const [zMin, zMax] = readHeightRange();
        const region = {
            id: crypto.randomUUID(),
            name: $('regionName').value.trim() || `Suspected artifact ${state.regions.length + 1}`,
            vertices: state.vertices.map(vertex => [...vertex]),
            zMin,
            zMax,
        };
        state.drawing = false;
        state.vertices = [];
        changeDraft(() => {
            state.regions.push(region);
            state.selectedId = region.id;
        });
        message('Added to the draft. Pink marks candidate display points only; there is no on-site free-space evidence.');
    } catch (error) {
        message(error.message, true);
    }
}

function cancelDrawing() {
    state.drawing = false;
    state.vertices = [];
    renderRegions();
    redrawOutlines();
    message('Unfinished polygon cancelled; saved regions are unchanged.');
}

function undoDraft(redo = false) {
    const source = redo ? state.redo : state.undo;
    const destination = redo ? state.undo : state.redo;
    if (state.drawing || !source.length) return;
    destination.push(snapshot());
    const previous = source.pop();
    state.regions = previous.regions;
    state.selectedId = previous.selectedId;
    const region = selectedRegion();
    if (region) {
        $('regionName').value = region.name;
        $('zMin').value = region.zMin;
        $('zMax').value = region.zMax;
    }
    refreshDraft();
    message(redo ? 'Redone.' : 'Undone.');
}

function bindInteractions() {
    bindDisplayHeight();
    $('draw').onclick = () => {
        try {
            $('zMin').value = state.displayMin.toFixed(2);
            $('zMax').value = state.displayMax.toFixed(2);
            readHeightRange();
            state.drawing = true;
            state.vertices = [];
            state.selectedId = null;
            $('regionName').value = `Suspected artifact ${state.regions.length + 1}`;
            setView('top');
            renderRegions();
            message('Left click adds vertices; right drag pans, wheel zooms; click “Finish polygon” when done.');
        } catch (error) {
            message(error.message, true);
        }
    };
    $('finish').onclick = finishPolygon;
    $('cancelDraw').onclick = cancelDrawing;
    $('undoVertex').onclick = () => {
        state.vertices.pop();
        redrawOutlines();
    };
    $('topView').onclick = () => setView('top');
    $('spatialView').onclick = () => setView('spatial');
    $('fitView').onclick = () => setView(viewMode, true);
    $('pointSize').oninput = () => { pointMaterial.size = Number($('pointSize').value); };
    $('hideCandidates').onchange = applyPreview;
    $('updateRegion').onclick = () => {
        try {
            const [zMin, zMax] = readHeightRange();
            const region = selectedRegion();
            if (!region) return;
            changeDraft(() => {
                region.zMin = zMin;
                region.zMax = zMax;
                region.name = $('regionName').value.trim() || 'Unnamed region';
            });
            message('Region name and height range updated.');
        } catch (error) {
            message(error.message, true);
        }
    };
    $('deleteRegion').onclick = () => changeDraft(() => {
        state.regions = state.regions.filter(region => region.id !== state.selectedId);
        state.selectedId = null;
    });
    $('undo').onclick = () => undoDraft();
    $('redo').onclick = () => undoDraft(true);
    $('clearDraft').onclick = async () => {
        if (!await ask('Clear draft', 'Clear all candidate regions on this page? Undo restores them; the map is not changed.')) return;
        changeDraft(() => {
            state.regions = [];
            state.selectedId = null;
        });
        message('Draft cleared; Undo restores it.');
    };
    $('exportDraft').onclick = () => {
        const blob = new Blob([JSON.stringify(draftDocument(), null, 2)], {type: 'application/json;charset=utf-8'});
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'map-correction-draft.json';
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        message('JSON draft download requested. It contains no map changes and no robot commands.');
    };
    $('importDraft').onclick = () => $('importFile').click();
    $('importFile').onchange = async () => {
        const file = $('importFile').files[0];
        $('importFile').value = '';
        if (!file) return;
        try {
            if (file.size > 1024 * 1024) throw new Error('The draft file exceeds 1 MiB; not imported.');
            const regions = validateDraft(JSON.parse(await file.text()));
            if (state.drawing) throw new Error('Finish or cancel the current polygon before importing.');
            changeDraft(() => {
                state.regions = regions;
                state.selectedId = null;
            });
            message('Imported a draft that matches this base map; Undo returns to the previous state.');
        } catch (error) {
            message('Import failed: ' + error.message, true);
        }
    };
    renderer.domElement.addEventListener('contextmenu', event => event.preventDefault());
    renderer.domElement.addEventListener('pointerdown', event => {
        pointerDown = event.button === 0 ? [event.clientX, event.clientY] : null;
    });
    renderer.domElement.addEventListener('pointercancel', () => { pointerDown = null; });
    renderer.domElement.addEventListener('pointermove', event => {
        if (!state.metadata || viewMode !== 'top') return;
        const point = mapPosition(event);
        if (point) $('cursorInfo').textContent = `Map X ${point.x.toFixed(3)} m · Y ${point.y.toFixed(3)} m · ${state.drawing ? 'drawing' : 'browsing'}`;
    });
    renderer.domElement.addEventListener('pointerup', event => {
        const down = pointerDown;
        pointerDown = null;
        if (!state.drawing || event.button !== 0 || !down || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 5) return;
        if (state.vertices.length >= MAX_VERTICES) {
            message(`At most ${MAX_VERTICES} vertices; finish or undo.`, true);
            return;
        }
        const point = mapPosition(event);
        if (!point) return;
        const low = state.metadata.bounds_min;
        const high = state.metadata.bounds_max;
        if (point.x < low[0] || point.x > high[0] || point.y < low[1] || point.y > high[1]) {
            message('Pick points inside the display map bounds.', true);
            return;
        }
        const vertex = [point.x, point.y];
        const previous = state.vertices[state.vertices.length - 1];
        if (previous && Math.hypot(vertex[0] - previous[0], vertex[1] - previous[1]) < 1e-6) return;
        state.vertices.push(vertex);
        redrawOutlines();
    });
    addEventListener('keydown', event => {
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName) || $('ask').open) return;
        if ((event.ctrlKey || event.metaKey) && event.code === 'KeyZ') {
            event.preventDefault();
            undoDraft(event.shiftKey);
        } else if (state.drawing && event.code === 'Enter') {
            event.preventDefault();
            finishPolygon();
        } else if (state.drawing && event.code === 'Escape') {
            cancelDrawing();
        } else if (state.drawing && event.code === 'Backspace') {
            event.preventDefault();
            state.vertices.pop();
            redrawOutlines();
        }
    });
    addEventListener('beforeunload', event => {
        if (state.drawing && state.vertices.length) {
            event.preventDefault();
            event.returnValue = '';
        }
    });
}

async function initialize() {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    renderer.setClearColor(0x000000, 0);   // the viewport's CSS gradient shows through
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.localClippingEnabled = true;
    $('viewport').append(renderer.domElement);
    scene = new THREE.Scene();
    camera = new THREE.OrthographicCamera(-20, 20, 20, -20, 0.01, 2000);
    camera.up.set(0, 0, 1);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.minZoom = 0.1;
    controls.maxZoom = 100;
    controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
    outlines = new THREE.Group();
    scene.add(outlines);
    const resize = () => {
        const width = $('viewport').clientWidth;
        const height = $('viewport').clientHeight;
        renderer.setSize(width, height);
        camera.left = -20 * width / height;
        camera.right = 20 * width / height;
        camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe($('viewport'));
    resize();
    const responses = await Promise.all([fetch('./navigation/map.json'), fetch('./navigation/map.bin')]);
    if (responses.some(response => !response.ok)) throw new Error('Reading the local map files failed.');
    const metadata = await responses[0].json();
    const buffer = await responses[1].arrayBuffer();
    if (!Number.isInteger(metadata.points) || metadata.points <= 0 || metadata.points > 4000000
        || buffer.byteLength !== metadata.points * 12 || metadata.format !== 'little-endian float32 XYZ'
        || typeof metadata.map !== 'string' || typeof metadata.frame !== 'string'
        || !/^[a-f0-9]{64}$/i.test(metadata.source_sha256 || '')) {
        throw new Error('Invalid map metadata, point count or source identity.');
    }
    for (const name of ['bounds_min', 'bounds_max']) {
        if (!Array.isArray(metadata[name]) || metadata[name].length !== 3 || !metadata[name].every(Number.isFinite)) {
            throw new Error('Invalid map bounds.');
        }
    }
    if (metadata.bounds_min.some((value, i) => value > metadata.bounds_max[i])) throw new Error('Map bounds are out of order.');
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    state.metadata = metadata;
    state.identity = {
        map: metadata.map,
        frame: metadata.frame,
        source_sha256: metadata.source_sha256,
        display_sha256: [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join(''),
    };
    state.storageKey = 'xt-map-correction:' + JSON.stringify(state.identity);
    state.positions = new Float32Array(buffer);
    state.baseColors = new Float32Array(state.positions.length);
    for (let i = 0; i < metadata.points; i++) {
        const offset = i * 3;
        if (![state.positions[offset], state.positions[offset + 1], state.positions[offset + 2]].every(Number.isFinite)) {
            throw new Error('The point cloud contains invalid coordinates; editing stopped.');
        }
        heightColor(state.positions[offset + 2], state.baseColors, offset);
    }
    pointGeometry = new THREE.BufferGeometry();
    pointGeometry.setAttribute('position', new THREE.BufferAttribute(state.positions, 3));
    pointGeometry.setAttribute('color', new THREE.BufferAttribute(state.baseColors.slice(), 3));
    pointMaterial = new THREE.PointsMaterial({
        size: 2.5,
        sizeAttenuation: false,
        vertexColors: true,
        clippingPlanes: heightClipPlanes,
    });
    const points = new THREE.Points(pointGeometry, pointMaterial);
    points.frustumCulled = false;
    scene.add(points);
    $('mapInfo').textContent = `Base map: ${metadata.map}\nFrame: ${metadata.frame}\nDisplay points: ${metadata.points.toLocaleString()}\nDisplay voxel: ${metadata.display_voxel_m} m\nZ range: ${metadata.bounds_min[2].toFixed(3)}–${metadata.bounds_max[2].toFixed(3)} m\nSource SHA256: ${metadata.source_sha256}`;
    let restoreError = null;
    try {
        const stored = localStorage.getItem(state.storageKey);
        if (stored) {
            const document = JSON.parse(stored);
            state.regions = validateDraft(document);
            if (typeof document.created_at === 'string' && Number.isFinite(Date.parse(document.created_at))) state.createdAt = document.created_at;
        }
    } catch (error) {
        restoreError = error;
        $('storageInfo').textContent = 'The stored browser draft was neither restored nor deleted: ' + error.message;
    }
    bindInteractions();
    setView('top', true);
    renderRegions();
    // Do not overwrite an unreadable existing draft until the operator makes a new edit.
    if (restoreError) {
        state.mask = new Uint8Array(metadata.points);
        renderCounts();
        message('Map loaded, but restoring the stored draft failed: ' + restoreError.message, true);
    } else {
        await updateCandidates();
        message(state.regions.length ? 'Restored the stored draft for this base map. All regions still need on-site confirmation.' : 'Map loaded. Click “New polygon” to start; the robot receives nothing from this page.');
    }
    renderer.setAnimationLoop(() => {
        controls.update();
        renderer.render(scene, camera);
    });
}

initialize().catch(error => {
    message('Editor not ready: ' + error.message + ' Open this page over local HTTP in a WebGL-capable browser.', true);
    for (const element of document.querySelectorAll('button, input')) element.disabled = true;
});
