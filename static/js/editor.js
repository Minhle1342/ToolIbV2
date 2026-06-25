class Editor {
    constructor(canvasId) {
        this.canvas = new fabric.Canvas(canvasId, {
            selection: false,
            uniScaleTransform: true, // Allow non-uniform scaling on corners
            preserveObjectStacking: true, // Important: Box z-index
            centeredScaling: false, // Fix: Do not scale from center
            selectionKey: 'ctrlKey' // Enable Ctrl+Click for multi-select
        });

        this.currentMode = 'select'; // 'select' | 'draw'
        this.currentClassId = 0;
        this.classes = []; // {id, name, color}
        this.isDrawing = false;
        this.isStickyMode = false;
        this.stickyObj = null;
        this.origX = 0;
        this.origY = 0;
        this.rect = null;
        this.imageWidth = 0;
        this.imageHeight = 0;
        this._loadSequence = 0; // Guard against stale image load callbacks

        // Undo/Redo API
        this.history = [];
        this.redoStack = [];
        this.historyProcessing = false;
        this.maxHistory = 50;
        this.onStateChange = null;
        this.loading = false;

        // Colors mapping
        this.colors = [
            '#FF3838', '#FF9D97', '#FF701F', '#FFB21D', '#CFD231',
            '#48F90A', '#92CC17', '#3DDB86', '#1A9334', '#00D4BB',
            '#2C99A8', '#00C2FF', '#344593', '#6473FF', '#0018EC',
            '#8438FF', '#520085', '#CB38FF', '#FF95C8', '#FF37C7'
        ];

        // Focus Mode state
        this.focusClassId = null;
        this.overlayCanvas = document.createElement('canvas');
        this.overlayCtx = this.overlayCanvas.getContext('2d');
        this.sequenceMode = 'none';
        this.showBoxes = true;
        this.isDirty = false;

        this.initEvents();
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());

        // Initialize Mode defaults
        this.setMode('select');
    }

    setFocusClass(id) {
        if (this.focusClassId === id) {
            this.focusClassId = null; // Toggle off
        } else {
            this.focusClassId = id;
        }
        this.canvas.requestRenderAll();
    }

    setClasses(classes) {
        this.classes = classes.map((name, index) => ({
            id: index,
            name: name,
            color: this.colors[index % this.colors.length]
        }));
    }

    resizeCanvas() {
        const wrapper = document.getElementById('canvasWrapper');
        this.canvas.setWidth(wrapper.clientWidth);
        this.canvas.setHeight(wrapper.clientHeight);
        this.centerImage();
    }

    centerImage() {
        if (this.backgroundImage) {
            // Ensure wrapper dimensions are up to date
            const wrapper = document.getElementById('canvasWrapper');
            const w = wrapper.clientWidth || 800;
            const h = wrapper.clientHeight || 600;

            if (this.canvas.width !== w || this.canvas.height !== h) {
                this.canvas.setWidth(w);
                this.canvas.setHeight(h);
            }

            const scale = Math.min(
                w / this.imageWidth,
                h / this.imageHeight
            ) * 0.95;

            this.canvas.setViewportTransform([scale, 0, 0, scale,
                (w - this.imageWidth * scale) / 2,
                (h - this.imageHeight * scale) / 2
            ]);
            this.canvas.requestRenderAll();
        }
    }

    loadImage(img) {
        this.imageWidth = img.width;
        this.imageHeight = img.height;
        this.backgroundImage = img;
        this.canvas.setBackgroundImage(img, this.canvas.renderAll.bind(this.canvas), {
            originX: 'left',
            originY: 'top'
        });

        // Use requestAnimationFrame to ensure DOM is ready for dimension calculation
        requestAnimationFrame(() => {
            this.centerImage();
        });
    }

    loadBoxes(boxes) {
        this.canvas.getObjects().forEach(o => {
            if (o.type === 'rect' || o.type === 'text' || o.type === 'group') this.canvas.remove(o);
        });

        boxes.forEach(box => {
            this.addBoxToCanvas(box.class_id, box.x, box.y, box.w, box.h, false, box.isOverlapping);
        });

        // Save initial state for Undo
        this.saveState();
        if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        this.focusClassId = null; // Reset focus on new image
        this.isDirty = false; // Reset dirty flag after initial load
    }

    addBoxToCanvas(classId, cx, cy, w, h, isNew = true, isOverlapping = false) {
        // Convert YOLO (normalized center xywh) to Canvas (top-left xywh)
        const left = (cx - w / 2) * this.imageWidth;
        const top = (cy - h / 2) * this.imageHeight;
        const width = w * this.imageWidth;
        const height = h * this.imageHeight;

        const cls = this.classes.find(c => c.id === classId) || { color: 'white' };

        const strokeColor = isOverlapping ? 'red' : cls.color;
        const fillColor = isOverlapping ? 'rgba(255, 0, 0, 0.3)' : 'rgba(0,0,0,0)';
        const strokeWidth = isOverlapping ? 3 / this.getZoom() : 1 / this.getZoom();

        const rect = new fabric.Rect({
            left: left,
            top: top,
            width: width,
            height: height,
            fill: fillColor,
            stroke: strokeColor,
            strokeWidth: strokeWidth,
            transparentCorners: false,
            cornerColor: 'white',
            cornerSize: 8,
            classId: classId,
            lockRotation: true,
            hasRotatingPoint: false,
            visible: this.showBoxes,
            evented: this.showBoxes,
            selectable: this.showBoxes && (this.currentMode === 'select')
        });

        // Z-Index Logic: Small boxes on top
        this.canvas.add(rect);
        this.sortBoxesByArea();

        if (isNew) this.canvas.setActiveObject(rect);
        this.canvas.requestRenderAll();
    }


    setMode(mode) {
        this.currentMode = mode;
        this.canvas.selection = (mode === 'select');

        if (mode === 'draw' || mode === 'auto_label_region') {
            this.canvas.discardActiveObject();
            this.canvas.requestRenderAll();
        }

        // Update UI buttons
        document.querySelectorAll('.btn-tool').forEach(b => b.classList.remove('active'));
        const btnDraw = document.getElementById('btnDraw');
        const btnSelect = document.getElementById('btnSelect');
        const btnRegion = document.getElementById('btnAutoLabelRegion');
        if (btnDraw) btnDraw.classList.toggle('active', mode === 'draw');
        if (btnSelect) btnSelect.classList.toggle('active', mode === 'select');
        if (btnRegion) btnRegion.classList.toggle('active', mode === 'auto_label_region');

        this.canvas.defaultCursor = (mode === 'draw' || mode === 'auto_label_region') ? 'crosshair' : 'default';
        this.canvas.forEachObject(o => {
            if (o.type === 'rect') o.selectable = (mode === 'select' && this.showBoxes);
        });
    }

    getZoom() {
        return this.canvas.getZoom();
    }

    renderMagnifier(obj) {
        const magCanvas = document.getElementById('magnifierCanvas');
        if (!magCanvas || !this.backgroundImage || !obj) return;

        const ctx = magCanvas.getContext('2d');
        const magPlaceholder = document.getElementById('magPlaceholder');

        magCanvas.style.display = 'block';
        magPlaceholder.style.display = 'none';

        // Scaled dimensions of the bounding box
        const sW = Math.abs(obj.width * obj.scaleX);
        const sH = Math.abs(obj.height * obj.scaleY);

        if (sW <= 0 || sH <= 0) {
            magCanvas.width = 300;
            magCanvas.height = 300;
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, 300, 300);
            return;
        }

        // Adjust canvas dimensions dynamically to preserve the aspect ratio of the bounding box
        const maxDim = 300;
        let tW = maxDim;
        let tH = maxDim;
        if (sW > sH) {
            tH = Math.round(maxDim * (sH / sW));
        } else {
            tW = Math.round(maxDim * (sW / sH));
        }

        magCanvas.width = tW;
        magCanvas.height = tH;

        // Fill with black background
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, tW, tH);

        const imgElement = this.backgroundImage._element;
        if (!imgElement) return;

        // Get the center of the bounding box (in original image coordinates)
        const center = obj.getCenterPoint();
        const theta = (obj.angle || 0) * Math.PI / 180;

        ctx.save();
        // Translate magnifier context origin to the center of the magnifier canvas
        ctx.translate(tW / 2, tH / 2);
        // Scale magnifier context to fit the bounding box dimensions
        ctx.scale(tW / sW, tH / sH);
        // Rotate magnifier context back by -theta to align the rotated bounding box upright
        ctx.rotate(-theta);
        // Translate magnifier context back relative to the bounding box center in image coordinates
        ctx.translate(-center.x, -center.y);

        // Draw the full original image (browser handles clipping to magnifier canvas area automatically)
        ctx.drawImage(imgElement, 0, 0);
        ctx.restore();
    }

    sortBoxesByArea() {
        const boxes = this.canvas.getObjects('rect');
        if (boxes.length <= 1) return;

        // Sort by area: Largest to Smallest
        boxes.sort((a, b) => {
            const areaA = (a.width * a.scaleX) * (a.height * a.scaleY);
            const areaB = (b.width * b.scaleX) * (b.height * b.scaleY);
            return areaB - areaA; // Descending: Large boxes first
        });

        // Move each box to the front in its sorted order
        // This effectively puts the largest box at the bottom and smallest at top
        boxes.forEach(box => {
            box.bringToFront();
        });

        this.canvas.requestRenderAll();
    }

    initEvents() {
        // Prevent middle click autoscroll on the canvas element
        if (this.canvas.upperCanvasEl) {
            this.canvas.upperCanvasEl.addEventListener('mousedown', (e) => {
                if (e.button === 1) {
                    e.preventDefault();
                    e.stopPropagation();
                }
            }, { passive: false });
        }

        this.canvas.on('mouse:down', (opt) => {
            if (this.isStickyMode && this.stickyObj) {
                this.toggleStickyMove(); // Click to drop
                return;
            }

            const evt = opt.e;
            if (evt.altKey === true || this.isSpacePressed === true || evt.button === 1) {
                this.isPanning = true;
                this.canvas.selection = false;
                this.lastPosX = evt.clientX;
                this.lastPosY = evt.clientY;
                return;
            }
            
            // Allow selecting hidden boxes by clicking anywhere inside their bounding box or sweeping
            if (!this.showBoxes) {
                // If user clicked on an already visible/active object, let Fabric handle it natively
                if (opt.target && (opt.target.type === 'rect' || opt.target.type === 'activeSelection')) {
                    return;
                }

                const pointer = this.canvas.getPointer(opt.e);
                
                // Store drag start coordinates for sweep selection
                this.sweepStartX = pointer.x;
                this.sweepStartY = pointer.y;

                const rects = this.canvas.getObjects('rect');
                let clickedRect = null;
                let minArea = Infinity;
                
                rects.forEach(rect => {
                    const left = rect.left;
                    const top = rect.top;
                    const width = rect.width * rect.scaleX;
                    const height = rect.height * rect.scaleY;
                    
                    if (pointer.x >= left && pointer.x <= left + width &&
                        pointer.y >= top && pointer.y <= top + height) {
                        
                        const area = width * height;
                        if (area < minArea) {
                            minArea = area;
                            clickedRect = rect;
                        }
                    }
                });
                
                if (clickedRect) {
                    clickedRect.set({
                        visible: true,
                        evented: true,
                        selectable: true
                    });
                    
                    this.setMode('select');
                    
                    if (evt.shiftKey || evt.ctrlKey || evt.metaKey) {
                        const activeObj = this.canvas.getActiveObject();
                        if (activeObj) {
                            let currentObjects = [];
                            if (activeObj.type === 'activeSelection') {
                                currentObjects = activeObj.getObjects();
                            } else {
                                currentObjects = [activeObj];
                            }
                            
                            const index = currentObjects.indexOf(clickedRect);
                            if (index > -1) {
                                currentObjects.splice(index, 1);
                            } else {
                                currentObjects.push(clickedRect);
                            }
                            
                            this.canvas.discardActiveObject();
                            
                            if (currentObjects.length === 1) {
                                this.canvas.setActiveObject(currentObjects[0]);
                            } else if (currentObjects.length > 1) {
                                const sel = new fabric.ActiveSelection(currentObjects, { canvas: this.canvas });
                                this.canvas.setActiveObject(sel);
                            }
                        } else {
                            this.canvas.setActiveObject(clickedRect);
                        }
                    } else {
                        this.canvas.discardActiveObject();
                        this.canvas.setActiveObject(clickedRect);
                    }
                    
                    return;
                }
            }

            if (this.currentMode === 'draw' || this.currentMode === 'auto_label_region') {
                // If user clicks on an existing box, switch to select mode
                if (this.currentMode === 'draw' && opt.target && opt.target.type === 'rect') {
                    this.setMode('select');
                    this.canvas.setActiveObject(opt.target);
                    // Manually fire selection event to update Inspector
                    this.onSelect({ selected: [opt.target] });
                    return;
                }

                this.isDrawing = true;
                const pointer = this.canvas.getPointer(opt.e);
                this.origX = pointer.x;
                this.origY = pointer.y;

                const strokeColor = this.currentMode === 'auto_label_region' ? '#a855f7' : (this.classes.find(c => c.id === this.currentClassId) || { color: 'red' }).color;
                const strokeDashArray = this.currentMode === 'auto_label_region' ? [5, 5] : null;

                this.rect = new fabric.Rect({
                    left: this.origX,
                    top: this.origY,
                    originX: 'left',
                    originY: 'top',
                    width: pointer.x - this.origX,
                    height: pointer.y - this.origY,
                    angle: 0,
                    fill: this.currentMode === 'auto_label_region' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(0,0,0,0)',
                    stroke: strokeColor,
                    strokeDashArray: strokeDashArray,
                    strokeWidth: 1 / this.getZoom(),
                    selectable: false, // temporarily false
                    classId: this.currentMode === 'auto_label_region' ? null : this.currentClassId
                });
                this.canvas.add(this.rect);
            }
        });

        this.canvas.on('mouse:move', (opt) => {
            if (this.isPanning) {
                const e = opt.e;
                const vpt = this.canvas.viewportTransform;
                vpt[4] += e.clientX - this.lastPosX;
                vpt[5] += e.clientY - this.lastPosY;
                this.canvas.requestRenderAll();
                this.lastPosX = e.clientX;
                this.lastPosY = e.clientY;
            } else if (this.isDrawing) {
                let pointer = this.canvas.getPointer(opt.e);

                // Clamp pointer to image bounds
                if (pointer.x < 0) pointer.x = 0;
                if (pointer.y < 0) pointer.y = 0;
                if (pointer.x > this.imageWidth) pointer.x = this.imageWidth;
                if (pointer.y > this.imageHeight) pointer.y = this.imageHeight;

                if (this.origX > pointer.x) {
                    this.rect.set({ left: Math.abs(pointer.x) });
                }
                if (this.origY > pointer.y) {
                    this.rect.set({ top: Math.abs(pointer.y) });
                }

                this.rect.set({ width: Math.abs(this.origX - pointer.x) });
                this.rect.set({ height: Math.abs(this.origY - pointer.y) });

                this.canvas.renderAll();
            } else if (this.isStickyMode && this.stickyObj) {
                let pointer = this.canvas.getPointer(opt.e);

                // Calculate potential new position
                let w = this.stickyObj.width * this.stickyObj.scaleX;
                let h = this.stickyObj.height * this.stickyObj.scaleY;

                let left = pointer.x - (w / 2);
                let top = pointer.y - (h / 2);

                // Clamp
                if (left < 0) left = 0;
                if (top < 0) top = 0;
                if (left + w > this.imageWidth) left = this.imageWidth - w;
                if (top + h > this.imageHeight) top = this.imageHeight - h;

                this.stickyObj.set({ left, top });
                this.stickyObj.setCoords();
                this.renderMagnifier(this.stickyObj);
                this.updateSelectionInfo(this.stickyObj);
                this.canvas.requestRenderAll();
            }
        });

        this.canvas.on('mouse:up', (opt) => {
            if (this.isPanning) {
                this.canvas.setViewportTransform(this.canvas.viewportTransform);
                this.isPanning = false;
                // Restore selection if in select mode
                this.canvas.selection = (this.currentMode === 'select');
            } else if (!this.showBoxes && this.sweepStartX !== undefined && this.sweepStartY !== undefined) {
                const pointer = this.canvas.getPointer(opt.e);
                const dx = Math.abs(pointer.x - this.sweepStartX);
                const dy = Math.abs(pointer.y - this.sweepStartY);
                
                if (dx > 5 || dy > 5) {
                    const minX = Math.min(this.sweepStartX, pointer.x);
                    const maxX = Math.max(this.sweepStartX, pointer.x);
                    const minY = Math.min(this.sweepStartY, pointer.y);
                    const maxY = Math.max(this.sweepStartY, pointer.y);
                    
                    const rects = this.canvas.getObjects('rect');
                    const selectedRects = [];
                    
                    rects.forEach(rect => {
                        const center = rect.getCenterPoint();
                        if (center.x >= minX && center.x <= maxX && center.y >= minY && center.y <= maxY) {
                            rect.set({ visible: true, evented: true, selectable: true });
                            selectedRects.push(rect);
                        }
                    });
                    
                    if (selectedRects.length > 0) {
                        this.setMode('select');
                        const evt = opt.e;
                        
                        let currentSelection = [];
                        if (evt.shiftKey || evt.ctrlKey || evt.metaKey) {
                            const activeObj = this.canvas.getActiveObject();
                            if (activeObj) {
                                if (activeObj.type === 'activeSelection') {
                                    currentSelection = activeObj.getObjects();
                                } else {
                                    currentSelection = [activeObj];
                                }
                            }
                        }
                        
                        // Combine and remove duplicates
                        const finalSelection = Array.from(new Set([...currentSelection, ...selectedRects]));
                        
                        this.canvas.discardActiveObject();
                        if (finalSelection.length === 1) {
                            this.canvas.setActiveObject(finalSelection[0]);
                        } else if (finalSelection.length > 1) {
                            const sel = new fabric.ActiveSelection(finalSelection, { canvas: this.canvas });
                            this.canvas.setActiveObject(sel);
                        }
                    }
                }
                
                this.sweepStartX = undefined;
                this.sweepStartY = undefined;
            } else if (this.isDrawing) {
                this.isDrawing = false;
                this.rect.setCoords();

                // If too small, remove
                if (this.rect.width < 5 || this.rect.height < 5) {
                    this.canvas.remove(this.rect);
                } else {
                    if (this.currentMode === 'auto_label_region') {
                        const region = {
                            x: this.rect.left,
                            y: this.rect.top,
                            w: this.rect.width,
                            h: this.rect.height
                        };
                        this.canvas.remove(this.rect);
                        this.setMode('select');
                        if (typeof currentWorkspace !== 'undefined' && currentWorkspace.autoLabelRegion) {
                            currentWorkspace.autoLabelRegion(region);
                        }
                    } else {
                        this.sortBoxesByArea();
                        // Auto-switch to select mode
                        this.setMode('select');
                        // Auto-select the new box
                        this.canvas.setActiveObject(this.rect);
                        this.onSelect({ selected: [this.rect] });
                    }
                }
                this.rect = null;
            }
        });

        // Key listeners for Panning
        document.addEventListener('keydown', (e) => {
            if (e.code === 'Space') {
                this.isSpacePressed = true;
                if (this.currentMode === 'draw') this.canvas.defaultCursor = 'grab';
            }
        });
        document.addEventListener('keyup', (e) => {
            if (e.code === 'Space') {
                this.isSpacePressed = false;
                if (this.currentMode === 'draw') this.canvas.defaultCursor = 'crosshair';
            }
        });

        // Panning with Scrollwheel (Zoom)
        this.canvas.on('mouse:wheel', (opt) => {
            if (opt.e.ctrlKey || opt.e.altKey) {
                const delta = opt.e.deltaY;
                let zoom = this.canvas.getZoom();
                zoom *= 0.999 ** delta;
                if (zoom > 20) zoom = 20;
                if (zoom < 0.01) zoom = 0.01;
                this.canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
                opt.e.preventDefault();
                opt.e.stopPropagation();
            }
        });

        // Selection Events
        this.canvas.on('selection:created', (e) => this.onSelect(e));
        this.canvas.on('selection:updated', (e) => this.onSelect(e));
        this.canvas.on('selection:cleared', (e) => this.onDeselect(e));

        // Double-click to highlight all boxes of the same class
        this.canvas.on('mouse:dblclick', (opt) => {
            if (opt.target && opt.target.type === 'rect') {
                const targetClassId = opt.target.classId;
                if (typeof targetClassId !== 'undefined' && targetClassId !== null) {
                    if (typeof selectClass === 'function') {
                        selectClass(targetClassId);
                    }
                }
            }
        });

        // Real-time update for magnifier
        this.canvas.on('object:moving', (e) => {
            if (e.target && e.target.type === 'rect') {
                const obj = e.target;

                // Constraint Logic
                let w = obj.width * obj.scaleX;
                let h = obj.height * obj.scaleY;
                let top = obj.top;
                let left = obj.left;

                if (top < 0) top = 0;
                if (left < 0) left = 0;
                if (top + h > this.imageHeight) top = this.imageHeight - h;
                if (left + w > this.imageWidth) left = this.imageWidth - w;

                obj.set({ top, left });

                this.renderMagnifier(obj);
                this.updateSelectionInfo(obj);
            }
        });
        this.canvas.on('object:scaling', (e) => {
            if (e.target && e.target.type === 'rect') {
                const obj = e.target;

                // For scaling, simple clamp might distort if Aspect Ratio is locked or not. 
                // Fabric usually keeps aspect ratio unless shift is pressed (or uniScale).
                // But preventing scaling OUT of bounds is tricky because you have to change scaleX/Y.
                // Easiest is to just clamp Top/Left if they moved, and if dimensions strictly exceed, limit scale?
                // Let's at least clamp position. Validating Scale is complex.
                // Users usually scale inside. If they scale out, we can try to clamp position.

                let w = obj.width * obj.scaleX;
                let h = obj.height * obj.scaleY;
                let top = obj.top;
                let left = obj.left;

                // If the box is ALREADY too big for image, limit?
                // Hard to perfect scaling constraints without complex math.
                // At least ensure Top-Left and Bottom-Right don't drift uncontrollably out.
                // We will just clamp selection box "moving" effect (top/left).

                if (top < 0) top = 0;
                if (left < 0) left = 0;
                // Don't force width/height constraint aggressively during scaling as it feels jittery

                obj.set({ top, left });

                this.renderMagnifier(obj);
                this.sortBoxesByArea();
                this.updateSelectionInfo(obj);
            }
        });

        this.canvas.on('object:rotating', (e) => {
            if (e.target && e.target.type === 'rect') {
                const obj = e.target;
                this.renderMagnifier(obj);
                this.updateSelectionInfo(obj);
            }
        });

        // History Hooks and Visibility Updates
        this.canvas.on('object:added', (e) => {
            if (e.target && e.target.type === 'rect' && !this.historyProcessing) this.saveState();
            if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        });
        this.canvas.on('object:modified', (e) => {
            if (e.target && (e.target.type === 'rect' || e.target.type === 'activeSelection') && !this.historyProcessing) this.saveState();
            if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        });
        this.canvas.on('object:removed', (e) => {
            if (e.target && e.target.type === 'rect' && !this.historyProcessing) this.saveState();
            if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        });

        // Focus Mode Dimming Overlay & Center Dots
        this.canvas.on('after:render', (opt) => {
            if (!this.showBoxes) {
                const ctx = opt.ctx || this.canvas.contextContainer;
                if (ctx) {
                    ctx.save();
                    const rects = this.canvas.getObjects('rect');
                    rects.forEach(rect => {
                        const cls = this.classes.find(c => c.id === rect.classId) || { color: '#00C2FF' };
                        const bound = rect.getBoundingRect();
                        const cx = bound.left + bound.width / 2;
                        const cy = bound.top + bound.height / 2;
                        
                        ctx.fillStyle = cls.color;
                        ctx.beginPath();
                        ctx.arc(cx, cy, 3, 0, Math.PI * 2);
                        ctx.fill();
                    });
                    ctx.restore();
                }
            }
            if (this.focusClassId !== null) {
                const ctx = opt.ctx || this.canvas.contextContainer;
                if (!ctx) return;

                const offCanvas = this.overlayCanvas;
                const offCtx = this.overlayCtx;

                // Match sizes if they got out of sync
                if (offCanvas.width !== this.canvas.width || offCanvas.height !== this.canvas.height) {
                    offCanvas.width = this.canvas.width;
                    offCanvas.height = this.canvas.height;
                }

                // Clear offscreen canvas
                offCtx.globalCompositeOperation = 'source-over';
                offCtx.clearRect(0, 0, offCanvas.width, offCanvas.height);

                // Fill with dimming color
                offCtx.fillStyle = 'rgba(0, 0, 0, 0.65)';
                offCtx.fillRect(0, 0, offCanvas.width, offCanvas.height);

                // Cut out the boxes
                offCtx.globalCompositeOperation = 'destination-out';
                offCtx.fillStyle = '#fff';
                const boxes = this.canvas.getObjects('rect').filter(o => o.classId === this.focusClassId);
                boxes.forEach(box => {
                    const bound = box.getBoundingRect();
                    offCtx.fillRect(bound.left, bound.top, bound.width, bound.height);
                });

                // Draw off-screen canvas to main canvas
                ctx.save();
                ctx.globalCompositeOperation = 'source-over';
                ctx.drawImage(offCanvas, 0, 0);
                ctx.restore();
            }

            if (this.sequenceMode && this.sequenceMode !== 'none' && this.showBoxes) {
                const ctx = opt.ctx || this.canvas.contextContainer;
                if (!ctx) return;

                ctx.save();
                const rects = this.canvas.getObjects('rect').filter(r =>
                    r.classId !== undefined &&
                    r.classId !== null &&
                    (this.focusClassId === null || r.classId === this.focusClassId)
                );

                const drawBadge = (numText, badgeColor, x, y, badgeTitle = null) => {
                    ctx.font = 'bold 11px sans-serif';
                    const textWidth = ctx.measureText(numText).width;
                    const badgeHeight = 16;
                    const badgeWidth = Math.max(badgeHeight, textWidth + 8);

                    ctx.fillStyle = badgeColor;
                    ctx.beginPath();
                    const radius = 3;
                    if (ctx.roundRect) {
                        ctx.roundRect(x, y, badgeWidth, badgeHeight, radius);
                    } else {
                        ctx.rect(x, y, badgeWidth, badgeHeight);
                    }
                    ctx.fill();

                    ctx.strokeStyle = '#ffffff';
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    let isLight = false;
                    if (badgeColor.startsWith('#')) {
                        const hex = badgeColor.substring(1);
                        const r = parseInt(hex.substring(0, 2), 16);
                        const g = parseInt(hex.substring(2, 4), 16);
                        const b = parseInt(hex.substring(4, 6), 16);
                        const brightness = (r * 299 + g * 587 + b * 114) / 1000;
                        if (brightness > 180) isLight = true;
                    }
                    ctx.fillStyle = isLight ? '#000000' : '#ffffff';

                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(numText, x + badgeWidth / 2, y + badgeHeight / 2);

                    if (badgeTitle) {
                        ctx.save();
                        ctx.font = 'bold 11px sans-serif';
                        const titleWidth = ctx.measureText(badgeTitle).width;
                        const titlePad = 6;
                        const titleHeight = 18;
                        const titleY = y - titleHeight - 4; // Margin bottom 4px

                        // Shadow for a premium look
                        ctx.shadowColor = 'rgba(0, 0, 0, 0.25)';
                        ctx.shadowBlur = 4;
                        ctx.shadowOffsetX = 0;
                        ctx.shadowOffsetY = 2;

                        ctx.fillStyle = '#FF8C00'; // Vibrant Dark Orange
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(x, titleY, titleWidth + titlePad * 2, titleHeight, 4);
                        } else {
                            ctx.rect(x, titleY, titleWidth + titlePad * 2, titleHeight);
                        }
                        ctx.fill();

                        // Reset shadow for text
                        ctx.shadowColor = 'transparent';
                        ctx.shadowBlur = 0;

                        ctx.fillStyle = '#ffffff';
                        ctx.fillText(badgeTitle, x + titleWidth / 2 + titlePad, titleY + titleHeight / 2);
                        ctx.restore();
                    }
                };

                if (this.sequenceMode === 'class') {
                    const rectsByClass = {};
                    rects.forEach(rect => {
                        const cid = rect.classId;
                        if (!rectsByClass[cid]) rectsByClass[cid] = [];
                        rectsByClass[cid].push(rect);
                    });

                    Object.keys(rectsByClass).forEach(cid => {
                        const classId = parseInt(cid);
                        const list = rectsByClass[cid];
                        list.sort((a, b) => a.top - b.top || a.left - b.left);
                        const cls = this.classes.find(c => c.id === classId) || { color: '#00C2FF' };

                        list.forEach((rect, index) => {
                            const bound = rect.getBoundingRect();
                            drawBadge((index + 1).toString(), cls.color, bound.left, bound.top);
                        });
                    });
                } else if (this.sequenceMode === 'column') {
                    // Thuật toán Graph-based Connected Components (Thành phần liên thông)
                    const n = rects.length;
                    const adj = Array.from({ length: n }, () => []);

                    for (let i = 0; i < n; i++) {
                        for (let j = i + 1; j < n; j++) {
                            const r1 = rects[i];
                            const r2 = rects[j];

                            // Giao thoa trục X
                            const minX1 = r1.left;
                            const maxX1 = r1.left + r1.width;
                            const minX2 = r2.left;
                            const maxX2 = r2.left + r2.width;
                            const overlapX = Math.max(0, Math.min(maxX1, maxX2) - Math.max(minX1, minX2));
                            const overlapRatioX1 = overlapX / r1.width;
                            const overlapRatioX2 = overlapX / r2.width;

                            // Giao thoa trục Y
                            const minY1 = r1.top;
                            const maxY1 = r1.top + r1.height;
                            const minY2 = r2.top;
                            const maxY2 = r2.top + r2.height;
                            const overlapY = Math.max(0, Math.min(maxY1, maxY2) - Math.max(minY1, minY2));
                            const overlapRatioY1 = overlapY / r1.height;
                            const overlapRatioY2 = overlapY / r2.height;

                            // Điều kiện nối cạnh (chung cột):
                            // 1. Giao thoa X > 30%
                            // 2. KHÔNG giao thoa Y quá lớn (<= 50%) để tránh gộp các box nằm ngang hàng (cùng 1 row)
                            if (Math.max(overlapRatioX1, overlapRatioX2) > 0.3) {
                                if (Math.max(overlapRatioY1, overlapRatioY2) <= 0.5) {
                                    adj[i].push(j);
                                    adj[j].push(i);
                                }
                            }
                        }
                    }

                    // Duyệt đồ thị tìm các Connected Components
                    const visited = new Array(n).fill(false);
                    const columns = [];

                    for (let i = 0; i < n; i++) {
                        if (!visited[i]) {
                            const compRects = [];
                            const queue = [i];
                            visited[i] = true;

                            while (queue.length > 0) {
                                const curr = queue.shift();
                                compRects.push(rects[curr]);

                                for (const neighbor of adj[curr]) {
                                    if (!visited[neighbor]) {
                                        visited[neighbor] = true;
                                        queue.push(neighbor);
                                    }
                                }
                            }

                            const minX = Math.min(...compRects.map(r => r.left));
                            const maxX = Math.max(...compRects.map(r => r.left + r.width));
                            columns.push({ rects: compRects, minX, maxX });
                        }
                    }

                    columns.sort((a, b) => a.minX - b.minX);
                    let globalIndex = 1;

                    columns.forEach((col, colIndex) => {
                        col.rects.sort((a, b) => a.top - b.top);

                        // Optionally draw a column bounding box (like the image shows a big orange/green box)
                        if (col.rects.length > 0) {
                            const minY = Math.min(...col.rects.map(r => r.getBoundingRect().top));
                            const maxY = Math.max(...col.rects.map(r => {
                                const b = r.getBoundingRect();
                                return b.top + b.height;
                            }));
                            // Subtle background fill
                            ctx.fillStyle = 'rgba(255, 140, 0, 0.05)';
                            ctx.fillRect(col.minX, minY, col.maxX - col.minX, maxY - minY);

                            // Dashed vivid border
                            ctx.strokeStyle = '#FF8C00'; // Dark Orange
                            ctx.lineWidth = 2;
                            ctx.setLineDash([6, 4]); // 6px dash, 4px gap
                            ctx.strokeRect(col.minX, minY, col.maxX - col.minX, maxY - minY);
                            ctx.setLineDash([]); // reset dash
                        }

                        col.rects.forEach((rect, idx) => {
                            const bound = rect.getBoundingRect();
                            const cls = this.classes.find(c => c.id === rect.classId) || { color: '#00C2FF' };
                            const badgeTitle = idx === 0 ? `Col ${colIndex + 1}` : null;
                            drawBadge(globalIndex.toString(), cls.color, bound.left, bound.top, badgeTitle);
                            globalIndex++;
                        });
                    });
                }

                ctx.restore();
            }
        });
    }

    onSelect(e) {
        if (!this.showBoxes) {
            if (e && e.deselected) {
                e.deselected.forEach(obj => {
                    if (obj.type === 'rect') {
                        obj.set({ visible: false, evented: false, selectable: false });
                    }
                });
            }
            if (e && e.selected) {
                e.selected.forEach(obj => {
                    if (obj.type === 'rect') {
                        obj.set({ visible: true, evented: true, selectable: true });
                    }
                });
            }
            this.canvas.requestRenderAll();
        }

        const activeObj = this.canvas.getActiveObject();
        if (!activeObj) return;

        // Verify it contains rects
        let hasRect = activeObj.type === 'rect';
        if (activeObj.type === 'activeSelection') {
            const objs = activeObj.getObjects();
            hasRect = objs.some(o => o.type === 'rect');
        }
        if (!hasRect) return;

        this.renderMagnifier(activeObj);
        this.updateSelectionInfo(activeObj);

        if (this.isIsolationMode) {
            this.updateIsolateView();
        }
    }

    updateSelectionInfo(obj) {
        if (!obj) return;

        // Resolve display object (first element if multiple selection)
        let displayObj = obj;
        if (obj.type === 'activeSelection' && typeof obj.getObjects === 'function') {
            const objs = obj.getObjects();
            if (objs && objs.length > 0) {
                displayObj = objs[0];
            }
        }

        // Update Right Sidebar
        const clsName = this.classes.find(c => c.id === displayObj.classId)?.name || 'Unknown';
        document.getElementById('selectionInfo').innerHTML = `
            <div class="mb-2">
                <label class="block text-xs text-gray-500 mb-0.5">Class</label>
                <span class="text-sm font-semibold text-gray-300">${clsName}</span>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs">
                 <div><span class="text-gray-500">X:</span> <span class="font-mono text-gray-300">${Math.round(obj.left)}</span></div>
                 <div><span class="text-gray-500">Y:</span> <span class="font-mono text-gray-300">${Math.round(obj.top)}</span></div>
                 <div><span class="text-gray-500">W:</span> <span class="font-mono text-gray-300">${Math.round(obj.width * obj.scaleX)}</span></div>
                 <div><span class="text-gray-500">H:</span> <span class="font-mono text-gray-300">${Math.round(obj.height * obj.scaleY)}</span></div>
            </div>
            <div class="mt-2 text-xs">
                <span class="${obj.lockMovementX ? 'text-yellow-500' : 'text-gray-600'}">
                    <i class="fa-solid fa-${obj.lockMovementX ? 'lock' : 'lock-open'}"></i> ${obj.lockMovementX ? 'Locked' : 'Unlocked'}
                </span>
            </div>
        `;
        document.getElementById('btnDeleteBox').style.display = 'block';
        const btnCollect = document.getElementById('btnCollectCrop');
        if (btnCollect) btnCollect.style.display = 'flex';
        const btnClassify = document.getElementById('btnClassifySelected');
        if (btnClassify) btnClassify.style.display = 'flex';
        if (typeof toggleBottomPanel === 'function') {
            toggleBottomPanel(true);
        }

        // Update Lock Button State
        const btnLock = document.getElementById('btnLock');
        if (btnLock) {
            if (obj.lockMovementX) {
                btnLock.classList.add('text-yellow-500');
                btnLock.classList.remove('text-gray-400');
                btnLock.querySelector('i').className = 'fa-solid fa-lock text-lg';
            } else {
                btnLock.classList.remove('text-yellow-500');
                btnLock.classList.add('text-gray-400');
                btnLock.querySelector('i').className = 'fa-solid fa-lock-open text-lg';
            }
        }
    }

    onDeselect(e) {
        document.getElementById('selectionInfo').innerHTML = 'Nothing selected';
        document.getElementById('btnDeleteBox').style.display = 'none';
        const btnCollect = document.getElementById('btnCollectCrop');
        if (btnCollect) btnCollect.style.display = 'none';
        const btnClassify = document.getElementById('btnClassifySelected');
        if (btnClassify) btnClassify.style.display = 'none';
        if (typeof toggleBottomPanel === 'function') {
            toggleBottomPanel(false);
        }

        const magCanvas = document.getElementById('magnifierCanvas');
        const magPlaceholder = document.getElementById('magPlaceholder');
        if (magCanvas) magCanvas.style.display = 'none';
        if (magPlaceholder) magPlaceholder.style.display = 'flex';

        // Also ensure rects are unselectable if in draw mode
        if (this.currentMode === 'draw') {
            this.canvas.forEachObject(o => o.selectable = false);
        }

        // Re-hide boxes if we are in hidden boxes mode
        if (!this.showBoxes) {
            if (e && e.deselected) {
                e.deselected.forEach(obj => {
                    if (obj.type === 'rect') {
                        obj.set({ visible: false, evented: false, selectable: false });
                    }
                });
            } else {
                const activeObjects = this.canvas.getActiveObjects();
                this.canvas.getObjects('rect').forEach(rect => {
                    if (!activeObjects.includes(rect)) {
                        rect.set({ visible: false, evented: false, selectable: false });
                    }
                });
            }
            this.canvas.requestRenderAll();
        }
    }

    /**
     * Select the next (or previous) bounding box in reading order:
     * top-to-bottom, left-to-right.
     * Pans the viewport to center the selected box on screen.
     * @param {boolean} reverse - If true, select the previous box instead.
     */
    selectNextBox(reverse = false) {
        if (!this.showBoxes) return;
        const boxes = this.canvas.getObjects('rect');
        if (boxes.length === 0) return;

        // Sort by top (Y) first, then by left (X) — reading order
        const sorted = [...boxes].sort((a, b) => {
            const dy = a.top - b.top;
            // Consider boxes within 10px of vertical distance as "same row"
            if (Math.abs(dy) > 10) return dy;
            return a.left - b.left;
        });

        // Ensure we are in select mode
        if (this.currentMode !== 'select') {
            this.setMode('select');
        }

        const current = this.canvas.getActiveObject();
        let nextIndex = 0;

        if (current && current.type === 'rect') {
            const currentIdx = sorted.indexOf(current);
            if (currentIdx !== -1) {
                if (reverse) {
                    nextIndex = (currentIdx - 1 + sorted.length) % sorted.length;
                } else {
                    nextIndex = (currentIdx + 1) % sorted.length;
                }
            }
        } else {
            // Nothing selected: pick first (Tab) or last (Shift+Tab)
            nextIndex = reverse ? sorted.length - 1 : 0;
        }

        const target = sorted[nextIndex];
        this.canvas.setActiveObject(target);
        this.onSelect({ selected: [target] });

        // Pan viewport to center the selected box on screen
        const zoom = this.canvas.getZoom();
        const boxCenterX = target.left + (target.width * target.scaleX) / 2;
        const boxCenterY = target.top + (target.height * target.scaleY) / 2;
        const vpw = this.canvas.getWidth();
        const vph = this.canvas.getHeight();

        const vpt = this.canvas.viewportTransform.slice(); // copy current transform
        vpt[4] = vpw / 2 - boxCenterX * zoom;
        vpt[5] = vph / 2 - boxCenterY * zoom;
        this.canvas.setViewportTransform(vpt);
    }

    deleteSelected() {
        const active = this.canvas.getActiveObjects();
        if (active.length) {
            this.canvas.discardActiveObject();
            active.forEach(obj => this.canvas.remove(obj));
        }
    }

    zoomIn() { this.canvas.setZoom(this.canvas.getZoom() * 1.1); }
    zoomOut() { this.canvas.setZoom(this.canvas.getZoom() * 0.9); }
    resetView() { this.centerImage(); }

    getBoxesYOLO() {
        // Convert all rects to YOLO format
        const boxes = [];
        this.canvas.getObjects().forEach(obj => {
            if (obj.type !== 'rect') return;

            // IMPORTANT: Use calcTransformMatrix() to get ABSOLUTE canvas coords.
            // getBoundingRect(true) returns WRONG coords when objects are inside
            // an activeSelection group (multi-select), causing bounding box drift on save.
            const matrix = obj.calcTransformMatrix();
            const w = Math.abs(obj.width * obj.scaleX);
            const h = Math.abs(obj.height * obj.scaleY);

            // Transform true center point (0,0 in object space) to absolute canvas coords
            const center = fabric.util.transformPoint({ x: 0, y: 0 }, matrix);

            const cx = center.x / this.imageWidth;
            const cy = center.y / this.imageHeight;
            const nw = w / this.imageWidth;
            const nh = h / this.imageHeight;

            boxes.push({
                class_id: obj.classId,
                x: cx,
                y: cy,
                w: nw,
                h: nh
            });
        });
        return boxes;
    }

    getSelectedBoxesInfo() {
        // Get info about ALL currently selected boxes (supports Ctrl+click multi-select)
        const activeObjects = this.canvas.getActiveObjects();
        if (!activeObjects || activeObjects.length === 0) return [];

        const results = [];
        activeObjects.forEach(obj => {
            if (obj.type !== 'rect') return;

            // IMPORTANT: When objects are in an activeSelection (multi-select),
            // getBoundingRect() returns RELATIVE coords within the group.
            // We must use calcTransformMatrix() to get ABSOLUTE canvas coords.
            const matrix = obj.calcTransformMatrix();
            const w = Math.abs(obj.width * obj.scaleX);
            const h = Math.abs(obj.height * obj.scaleY);

            // Transform the true center point (0,0 in object space) to absolute coords
            const center = fabric.util.transformPoint({ x: 0, y: 0 }, matrix);

            const cx = center.x / this.imageWidth;
            const cy = center.y / this.imageHeight;
            const nw = w / this.imageWidth;
            const nh = h / this.imageHeight;

            const cls = this.classes.find(c => c.id === obj.classId);

            results.push({
                class_id: obj.classId,
                class_name: cls ? cls.name : `Class_${obj.classId}`,
                x: cx,
                y: cy,
                w: nw,
                h: nh
            });
        });
        return results;
    }

    updateActiveBoxesClasses(predictions) {
        // predictions is an array of { class_id, class_name, confidence } matching the active objects order
        const activeObjects = this.canvas.getActiveObjects();
        if (!activeObjects || activeObjects.length !== predictions.length) return;

        let changedCount = 0;
        activeObjects.forEach((obj, idx) => {
            if (obj.type !== 'rect') return;

            const pred = predictions[idx];
            if (pred && pred.class_id !== undefined && !pred.error) {
                obj.classId = pred.class_id;

                // Update color
                const cls = this.classes.find(c => c.id === pred.class_id);
                if (cls) {
                    obj.set({
                        stroke: cls.color,
                        cornerColor: cls.color,
                        borderColor: cls.color
                    });

                    // Add confidence tooltip/label if needed
                    obj.label = `${cls.name} (${(pred.confidence * 100).toFixed(1)}%)`;
                }
                changedCount++;
            }
        });

        if (changedCount > 0) {
            this.canvas.requestRenderAll();
            this.updateSelectionInfo(this.canvas.getActiveObject());
        }
    }

    getAllBoxesWithClassNames() {
        // Get all boxes with class names (for batch collect)
        const boxes = [];
        this.canvas.getObjects().forEach(obj => {
            if (obj.type !== 'rect') return;

            const rect = obj.getBoundingRect(true);
            const cx = (rect.left + rect.width / 2) / this.imageWidth;
            const cy = (rect.top + rect.height / 2) / this.imageHeight;
            const nw = rect.width / this.imageWidth;
            const nh = rect.height / this.imageHeight;

            const cls = this.classes.find(c => c.id === obj.classId);

            boxes.push({
                class_id: obj.classId,
                class_name: cls ? cls.name : `Class_${obj.classId}`,
                x: cx,
                y: cy,
                w: nw,
                h: nh
            });
        });
        return boxes;
    }

    toggleLockBox() {
        // Toggle lock for ALL selected objects
        const activeObjects = this.canvas.getActiveObjects();
        if (!activeObjects || activeObjects.length === 0) return;

        let anyLocked = activeObjects.some(obj => obj.lockMovementX === true);
        const newState = !anyLocked; // Toggle state

        activeObjects.forEach(obj => {
            if (obj.type === 'rect') {
                obj.lockMovementX = newState;
                obj.lockMovementY = newState;
                obj.lockScalingX = newState;
                obj.lockScalingY = newState;
                obj.lockRotation = newState;
                obj.hasControls = !newState; // Hide controls when locked for cleaner look? Yes.

                // Visual cue
                if (newState) {
                    obj.strokeDashArray = [4, 4]; // Dashed line implies locked/static
                } else {
                    obj.strokeDashArray = null;
                }
            }
        });

        this.canvas.requestRenderAll();
        // Force update UI if single selection
        if (activeObjects.length === 1) {
            this.onSelect({ selected: [activeObjects[0]] });
        }
    }

    updateIsolateView() {
        const activeObjects = this.canvas.getActiveObjects();

        this.canvas.getObjects().forEach(obj => {
            if (obj.type !== 'rect') return;

            if (this.isIsolationMode) {
                // Dim or hide others
                if (activeObjects.includes(obj)) {
                    obj.opacity = 1;
                    obj.selectable = this.showBoxes && (this.currentMode === 'select');
                    obj.evented = this.showBoxes;
                    obj.visible = this.showBoxes;
                } else {
                    obj.opacity = 0;
                    obj.selectable = false;
                    obj.evented = false;
                    obj.visible = false;
                }
            } else {
                // Restore All
                obj.opacity = 1;
                obj.selectable = this.showBoxes && (this.currentMode === 'select');
                obj.evented = this.showBoxes;
                obj.visible = this.showBoxes;
            }
        });

        this.canvas.requestRenderAll();
    }

    toggleIsolateMode() {
        // Toggle Isolation
        this.isIsolationMode = !this.isIsolationMode;

        this.updateIsolateView();

        // Visual cue for button?
        const btn = document.getElementById('btnIsolate');
        if (btn) {
            if (this.isIsolationMode) {
                btn.classList.add('text-yellow-500');
                btn.classList.remove('text-gray-400');
            } else {
                btn.classList.remove('text-yellow-500');
                btn.classList.add('text-gray-400');
            }
        }
    }
    toggleImageVisibility() {
        if (!this.backgroundImage) return;

        // Use opacity instead of visible=false to keep dimensions for centering/pan
        // Or actually visible=false is fine if we check resizing logic. 
        // centerImage() logic uses imageWidth/Height stored properties, so it should be safe.
        // But let's use opacity for smoother effect or ghosting? No, full hide is better to see trash.

        const current = this.canvas.backgroundImage.opacity;
        const newOpacity = current === 0 ? 1 : 0;

        this.canvas.backgroundImage.set('opacity', newOpacity);
        this.canvas.requestRenderAll();

        // Update Button UI
        const btn = document.getElementById('btnHideImage');
        if (btn) {
            if (newOpacity === 0) {
                btn.classList.add('text-red-500');
                btn.classList.remove('text-green-500', 'text-gray-400');
            } else {
                btn.classList.add('text-green-500');
                btn.classList.remove('text-red-500');
            }
        }
    }

    setSequenceMode(mode) {
        this.sequenceMode = mode;
        this.canvas.requestRenderAll();
        return mode !== 'none';
    }

    toggleBoxesVisibility() {
        this.showBoxes = !this.showBoxes;
        if (!this.showBoxes && this.isIsolationMode) {
            // Turn off isolation mode if we are hiding boxes
            this.isIsolationMode = false;
            const btn = document.getElementById('btnIsolate');
            if (btn) {
                btn.classList.remove('text-yellow-500');
                btn.classList.add('text-gray-400');
            }
        }
        this.canvas.forEachObject(obj => {
            if (obj.type === 'rect') {
                obj.set({
                    visible: this.showBoxes,
                    opacity: 1, // Reset opacity in case it was isolated
                    evented: this.showBoxes,
                    selectable: this.showBoxes && (this.currentMode === 'select')
                });
            }
        });
        if (!this.showBoxes) {
            this.canvas.discardActiveObject();
        }
        this.canvas.requestRenderAll();
        return this.showBoxes;
    }

    setActiveClass(id) {
        this.currentClassId = id;

        // If boxes are selected, update their class immediately
        const activeObjects = this.canvas.getActiveObjects(); // Works for single and multi
        if (activeObjects.length > 0) {
            const cls = this.classes.find(c => c.id === id) || { color: 'white' };

            activeObjects.forEach(obj => {
                if (obj.type === 'rect') {
                    obj.set({
                        stroke: cls.color,
                        classId: id
                    });
                }
            });

            this.canvas.requestRenderAll();
            if (activeObjects.length === 1) {
                this.onSelect({ selected: [activeObjects[0]] });
            }
            if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
            this.saveState();
        }
    }

    duplicateSelected() {
        const activeObjects = this.canvas.getActiveObjects();
        if (!activeObjects || activeObjects.length === 0) return;

        this.canvas.discardActiveObject();

        const newObjects = [];

        activeObjects.forEach(obj => {
            if (obj.type === 'rect') {
                obj.clone((cloned) => {
                    cloned.set({
                        left: obj.left + 20,
                        top: obj.top + 20,
                        classId: obj.classId, // Explicitly copy custom property
                        stroke: obj.stroke,
                        evented: true,
                        // Reset locks for copy
                        lockMovementX: false,
                        lockMovementY: false,
                        lockScalingX: false,
                        lockScalingY: false,
                        lockRotation: false,
                        hasControls: true,
                        strokeDashArray: null
                    });

                    this.canvas.add(cloned);
                    newObjects.push(cloned);

                    // If this was the last one, maintain selection of new objects
                    if (newObjects.length === activeObjects.length) {
                        if (newObjects.length === 1) {
                            this.canvas.setActiveObject(newObjects[0]);
                        } else {
                            const sel = new fabric.ActiveSelection(newObjects, {
                                canvas: this.canvas,
                            });
                            this.canvas.setActiveObject(sel);
                        }
                        this.canvas.requestRenderAll();
                        this.sortBoxesByArea();

                        // Auto-Sticky Feature
                        // Can't just call toggleStickyMove() because it toggles. We want Force Enable.
                        this.isStickyMode = true;
                        this.stickyObj = this.canvas.getActiveObject();
                        this.canvas.defaultCursor = 'move';
                    }
                }, ['classId', 'lockMovementX', 'lockMovementY', 'lockScalingX', 'lockScalingY', 'lockRotation', 'hasControls', 'strokeDashArray']); // Properties to include in clone
            }
        });
    }

    toggleStickyMove() {
        if (this.isStickyMode) {
            // Disable
            this.isStickyMode = false;
            if (this.stickyObj) {
                this.stickyObj.set('opacity', 1); // Restore opacity just in case
                this.stickyObj = null;
            }
            this.canvas.defaultCursor = 'default';
        } else {
            // Enable
            const active = this.canvas.getActiveObject();
            if (active && active.type === 'rect') {
                this.isStickyMode = true;
                this.stickyObj = active;
                this.canvas.defaultCursor = 'move';

                // Snap immediately to cursor? 
                // We can't easily get cursor pos here without an event, 
                // so we wait for first mouse move or ignore.

                // Maybe slight visual cue?
                // active.set('opacity', 0.8); 
            }
        }
    }
    // --- Undo/Redo ---
    saveState() {
        if (this.historyProcessing) return;

        this.isDirty = true;

        // Save current state
        const state = JSON.stringify(this.canvas.toDatalessJSON([
            'classId',
            'lockMovementX', 'lockMovementY',
            'lockScalingX', 'lockScalingY',
            'lockRotation',
            'hasControls', 'strokeDashArray'
        ]));

        // Avoid duplicate states (e.g. slight moves)
        if (this.history.length > 0 && this.history[this.history.length - 1] === state) {
            return;
        }

        this.history.push(state);
        if (this.history.length > this.maxHistory) this.history.shift();
        this.redoStack = []; // Clear redo

        if (!this.loading && typeof this.onStateChange === 'function') {
            this.onStateChange();
        }
    }

    undo() {
        if (this.history.length === 0) return;

        this.historyProcessing = true;

        const currentState = JSON.stringify(this.canvas.toDatalessJSON([
            'classId', 'lockMovementX', 'lockMovementY', 'lockScalingX', 'lockScalingY', 'lockRotation', 'hasControls', 'strokeDashArray'
        ]));
        this.redoStack.push(currentState);

        const prevState = this.history.pop();
        this.loadState(prevState);
    }

    redo() {
        if (this.redoStack.length === 0) return;

        this.historyProcessing = true;

        const currentState = JSON.stringify(this.canvas.toDatalessJSON([
            'classId', 'lockMovementX', 'lockMovementY', 'lockScalingX', 'lockScalingY', 'lockRotation', 'hasControls', 'strokeDashArray'
        ]));
        this.history.push(currentState);

        const nextState = this.redoStack.pop();
        this.loadState(nextState);
    }

    loadState(json) {
        this.canvas.loadFromJSON(json, () => {
            this.canvas.renderAll();
            this.historyProcessing = false;

            if (this.canvas.backgroundImage) {
                this.backgroundImage = this.canvas.backgroundImage;
            }

            if (!this.loading && typeof this.onStateChange === 'function') {
                this.onStateChange();
            }
        });
    }

    triggerGlowForClasses(classIds) {
        const rects = this.canvas.getObjects('rect');
        if (rects.length === 0) return;

        // If classIds is empty or null, default to all rects
        const targets = (!classIds || classIds.length === 0)
            ? rects
            : rects.filter(r => classIds.includes(r.classId));

        if (targets.length === 0) return;

        // Save original strokeWidths and shadows
        const originals = targets.map(r => ({
            obj: r,
            strokeWidth: r.strokeWidth,
            shadow: r.shadow
        }));

        // Pulse duration of 2 seconds
        const startTime = Date.now();
        const duration = 2000;

        const animate = () => {
            const now = Date.now();
            const elapsed = now - startTime;
            if (elapsed >= duration) {
                // Restore originals perfectly
                originals.forEach(item => {
                    item.obj.set({
                        strokeWidth: item.strokeWidth,
                        shadow: item.shadow
                    });
                });
                this.canvas.requestRenderAll();
                return;
            }

            // Pulsing factor between 0 and 1
            // 2s duration, pulse 3 times: frequency = 3 * 2 * PI / 2000 = 3 * PI / 1000
            const pulse = (Math.sin((elapsed * Math.PI * 3) / 1000) + 1) / 2; // ranges from 0 to 1

            targets.forEach(r => {
                const blurValue = pulse * 20; // max 20 blur
                const extraStroke = pulse * 3; // max +3px strokeWidth
                const baseColor = r.stroke || '#ffffff';

                r.set({
                    strokeWidth: 1 / this.getZoom() + extraStroke,
                    shadow: new fabric.Shadow({
                        color: baseColor,
                        blur: blurValue,
                        offsetX: 0,
                        offsetY: 0,
                        affectStroke: true
                    })
                });
            });

            this.canvas.requestRenderAll();
            requestAnimationFrame(animate);
        };

        requestAnimationFrame(animate);
    }
}
