"use strict";

const viewport = document.querySelector("#viewport");
const world = document.querySelector("#world");
const photo = document.querySelector("#photo");
const overlay = document.querySelector("#overlay");
const context = overlay.getContext("2d", { alpha: true });
const classSelect = document.querySelector("#class");
const classColor = document.querySelector("#class-color");
const brushInput = document.querySelector("#brush");
const brushSize = document.querySelector("#brush-size");
const undoButton = document.querySelector("#undo");
const saveButton = document.querySelector("#save");
const status = document.querySelector("#status");

let width = 0;
let height = 0;
let mask;
let palette = [];
let scale = 1;
let minimumScale = 1;
let offsetX = 0;
let offsetY = 0;
let penPoint = null;
let activePen = null;
let gesture = null;
let changed = false;
const touches = new Map();
const undoStack = [];

/** Set the status shown above the editor. @param {string} message Text to show. @returns {void} */
function setStatus(message) {
  status.textContent = message;
}

/** Paint a rectangular area from class IDs into the translucent overlay. @param {number} left Left pixel. @param {number} top Top pixel. @param {number} right Exclusive right pixel. @param {number} bottom Exclusive bottom pixel. @returns {void} */
function renderRegion(left, top, right, bottom) {
  const regionWidth = right - left;
  const regionHeight = bottom - top;
  if (regionWidth <= 0 || regionHeight <= 0) return;
  const pixels = context.createImageData(regionWidth, regionHeight);
  for (let y = 0; y < regionHeight; y++) {
    for (let x = 0; x < regionWidth; x++) {
      const id = mask[(top + y) * width + left + x];
      if (id === 0) continue;
      const index = (y * regionWidth + x) * 4;
      const color = palette[id];
      pixels.data[index] = color[0];
      pixels.data[index + 1] = color[1];
      pixels.data[index + 2] = color[2];
      pixels.data[index + 3] = 145;
    }
  }
  context.putImageData(pixels, left, top);
}

/** Apply the current scale and translation to the image and mask together. @returns {void} */
function updateTransform() {
  world.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`;
}

/** Convert a browser pointer position to image pixel coordinates. @param {PointerEvent|object} point Pointer with clientX/clientY. @returns {{x:number,y:number}} Image coordinates. */
function imagePoint(point) {
  const bounds = viewport.getBoundingClientRect();
  return {
    x: (point.clientX - bounds.left - offsetX) / scale,
    y: (point.clientY - bounds.top - offsetY) / scale,
  };
}

/** Fit the working image within the available iPad viewport. @returns {void} */
function fitImage() {
  if (!width || !height) return;
  minimumScale = Math.min(viewport.clientWidth / width, viewport.clientHeight / height);
  scale = minimumScale;
  offsetX = (viewport.clientWidth - width * scale) / 2;
  offsetY = (viewport.clientHeight - height * scale) / 2;
  updateTransform();
}

/** Save one snapshot before a Pencil stroke for Undo. @returns {void} */
function rememberStroke() {
  undoStack.push(mask.slice());
  if (undoStack.length > 10) undoStack.shift();
  undoButton.disabled = false;
}

/** Paint the pixels covered by a round line segment. @param {{x:number,y:number}} start First image point. @param {{x:number,y:number}} end Last image point. @returns {void} */
function paintSegment(start, end) {
  const radius = Math.max(0.75, Number(brushInput.value) / 2);
  const left = Math.max(0, Math.floor(Math.min(start.x, end.x) - radius));
  const top = Math.max(0, Math.floor(Math.min(start.y, end.y) - radius));
  const right = Math.min(width, Math.ceil(Math.max(start.x, end.x) + radius));
  const bottom = Math.min(height, Math.ceil(Math.max(start.y, end.y) + radius));
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  const id = Number(classSelect.value);

  // Rasterize in image coordinates so a brush remains precise at every zoom.
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const projection = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
        ((x + 0.5 - start.x) * dx + (y + 0.5 - start.y) * dy) / lengthSquared));
      const nearestX = start.x + projection * dx;
      const nearestY = start.y + projection * dy;
      const distanceSquared = (x + 0.5 - nearestX) ** 2 + (y + 0.5 - nearestY) ** 2;
      if (distanceSquared <= radius * radius) mask[y * width + x] = id;
    }
  }
  renderRegion(left, top, right, bottom);
  changed = true;
  setStatus("Unsaved corrections");
}

/** Record the current finger positions as a new pan or pinch starting point. @returns {void} */
function resetGesture() {
  const points = [...touches.values()];
  if (points.length === 1) {
    gesture = { kind: "pan", x: points[0].clientX, y: points[0].clientY };
  } else if (points.length >= 2) {
    const centerX = (points[0].clientX + points[1].clientX) / 2;
    const centerY = (points[0].clientY + points[1].clientY) / 2;
    const bounds = viewport.getBoundingClientRect();
    gesture = {
      kind: "pinch",
      distance: Math.hypot(points[0].clientX - points[1].clientX, points[0].clientY - points[1].clientY),
      scale,
      imageX: (centerX - bounds.left - offsetX) / scale,
      imageY: (centerY - bounds.top - offsetY) / scale,
    };
  } else {
    gesture = null;
  }
}

/** Move or zoom the image using the active finger gesture. @returns {void} */
function updateGesture() {
  const points = [...touches.values()];
  if (points.length === 1 && gesture?.kind === "pan") {
    offsetX += points[0].clientX - gesture.x;
    offsetY += points[0].clientY - gesture.y;
    gesture.x = points[0].clientX;
    gesture.y = points[0].clientY;
  } else if (points.length >= 2 && gesture?.kind === "pinch") {
    const centerX = (points[0].clientX + points[1].clientX) / 2;
    const centerY = (points[0].clientY + points[1].clientY) / 2;
    const distance = Math.hypot(points[0].clientX - points[1].clientX, points[0].clientY - points[1].clientY);
    const bounds = viewport.getBoundingClientRect();
    scale = Math.max(minimumScale, Math.min(16, gesture.scale * distance / Math.max(1, gesture.distance)));
    // Keep the image pixel beneath the pinch center anchored as fingers move.
    offsetX = centerX - bounds.left - gesture.imageX * scale;
    offsetY = centerY - bounds.top - gesture.imageY * scale;
  }
  updateTransform();
}

viewport.addEventListener("pointerdown", event => {
  if (event.pointerType === "touch") {
    if (activePen !== null) return; // Ignore palm contacts during a Pencil stroke.
    touches.set(event.pointerId, event);
    viewport.setPointerCapture(event.pointerId);
    resetGesture();
  } else if (event.pointerType === "pen" || event.pointerType === "mouse") {
    if (!mask || activePen !== null || event.button !== 0) return;
    touches.clear(); // A palm resting on the screen must not pan during ink.
    gesture = null;
    activePen = event.pointerId;
    penPoint = imagePoint(event);
    viewport.setPointerCapture(event.pointerId);
    rememberStroke();
    paintSegment(penPoint, penPoint);
  }
});

viewport.addEventListener("pointermove", event => {
  if (event.pointerId === activePen) {
    const next = imagePoint(event);
    paintSegment(penPoint, next);
    penPoint = next;
  } else if (activePen === null && touches.has(event.pointerId)) {
    touches.set(event.pointerId, event);
    updateGesture();
  }
});

/** Finish a Pencil stroke or finger gesture. @param {PointerEvent} event Ending pointer. @returns {void} */
function endPointer(event) {
  if (event.pointerId === activePen) {
    activePen = null;
    penPoint = null;
  }
  if (touches.delete(event.pointerId)) resetGesture();
}
viewport.addEventListener("pointerup", endPointer);
viewport.addEventListener("pointercancel", endPointer);

brushInput.addEventListener("input", () => { brushSize.textContent = `${brushInput.value} px`; });
classSelect.addEventListener("change", () => {
  const color = palette[Number(classSelect.value)];
  classColor.style.background = Number(classSelect.value) === 0 ? "transparent" : `rgb(${color.join(",")})`;
});
undoButton.addEventListener("click", () => {
  if (!undoStack.length) return;
  mask = undoStack.pop();
  undoButton.disabled = undoStack.length === 0;
  renderRegion(0, 0, width, height);
  changed = true;
  setStatus("Unsaved corrections");
});

saveButton.addEventListener("click", async () => {
  saveButton.disabled = true;
  setStatus("Saving…");
  const snapshot = mask.slice();
  try {
    const response = await fetch("/api/mask", {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: snapshot,
    });
    if (!response.ok) throw new Error(await response.text());
    changed = !mask.every((id, index) => id === snapshot[index]);
    setStatus(changed ? "Saved; newer corrections remain" : "Mask saved on host");
  } catch (error) {
    setStatus(`Save failed: ${error.message}`);
  } finally {
    saveButton.disabled = false;
  }
});

window.addEventListener("beforeunload", event => {
  if (!changed) return;
  event.preventDefault();
  event.returnValue = "";
});

/** Load the current image, class names, and class ID mask from the server. @returns {Promise<void>} */
async function start() {
  try {
    const [sessionResponse, maskResponse] = await Promise.all([
      fetch("/api/session"), fetch("/api/mask"),
    ]);
    if (!sessionResponse.ok || !maskResponse.ok) throw new Error("Could not load the session");
    const session = await sessionResponse.json();
    width = session.width;
    height = session.height;
    mask = new Uint8Array(await maskResponse.arrayBuffer());
    if (mask.length !== width * height) throw new Error("Mask size does not match image");
    palette = session.palette;
    session.classes.forEach((name, id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = `${id}: ${name === "__background__" ? "background / erase" : name}`;
      classSelect.append(option);
    });
    classSelect.value = session.classes.length > 1 ? "1" : "0";
    classSelect.dispatchEvent(new Event("change"));
    world.style.width = `${width}px`;
    world.style.height = `${height}px`;
    photo.width = width;
    photo.height = height;
    overlay.width = width;
    overlay.height = height;
    photo.src = "/api/image";
    await photo.decode();
    renderRegion(0, 0, width, height);
    fitImage();
    saveButton.disabled = false;
    setStatus("Ready. Choose a class and draw with Pencil.");
  } catch (error) {
    setStatus(`Could not start: ${error.message}`);
    saveButton.disabled = true;
  }
}

start();
window.addEventListener("resize", fitImage);
