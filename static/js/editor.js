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

        // Undo/Redo API
        this.history = [];
        this.redoStack = [];
        this.historyProcessing = false;
        this.maxHistory = 50;

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
            this.addBoxToCanvas(box.class_id, box.x, box.y, box.w, box.h, false);
        });

        // Save initial state for Undo
        this.saveState();
        if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        this.focusClassId = null; // Reset focus on new image
    }

    addBoxToCanvas(classId, cx, cy, w, h, isNew = true) {
        // Convert YOLO (normalized center xywh) to Canvas (top-left xywh)
        const left = (cx - w / 2) * this.imageWidth;
        const top = (cy - h / 2) * this.imageHeight;
        const width = w * this.imageWidth;
        const height = h * this.imageHeight;

        const cls = this.classes.find(c => c.id === classId) || { color: 'white' };

        const rect = new fabric.Rect({
            left: left,
            top: top,
            width: width,
            height: height,
            fill: 'rgba(0,0,0,0)',
            stroke: cls.color,
            strokeWidth: 2 / this.getZoom(), // Dynamic stroke?
            transparentCorners: false,
            cornerColor: 'white',
            cornerSize: 8,
            classId: classId
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

        if (mode === 'draw') {
            this.canvas.discardActiveObject();
            this.canvas.requestRenderAll();
        }

        // Update UI buttons
        document.querySelectorAll('.btn-tool').forEach(b => b.classList.remove('active'));
        if (mode === 'draw') document.getElementById('btnDraw').classList.add('active');
        if (mode === 'select') document.getElementById('btnSelect').classList.add('active');

        this.canvas.defaultCursor = mode === 'draw' ? 'crosshair' : 'default';
        this.canvas.forEachObject(o => {
            if (o.type === 'rect') o.selectable = (mode === 'select');
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

        // Source dimensions (from original image)
        const sX = obj.left;
        const sY = obj.top;
        const sW = obj.width * obj.scaleX;
        const sH = obj.height * obj.scaleY;

        // Target canvas dimensions
        const tW = magCanvas.width = 300; // Fixed resolution for zoom
        const tH = magCanvas.height = 300;

        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, tW, tH);

        const imgElement = this.backgroundImage._element;
        if (!imgElement) return;

        ctx.drawImage(imgElement, sX, sY, sW, sH, 0, 0, tW, tH);
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
        this.canvas.on('mouse:down', (opt) => {
            if (this.isStickyMode && this.stickyObj) {
                this.toggleStickyMove(); // Click to drop
                return;
            }

            const evt = opt.e;
            if (evt.altKey === true || this.isSpacePressed === true) {
                this.isPanning = true;
                this.canvas.selection = false;
                this.lastPosX = evt.clientX;
                this.lastPosY = evt.clientY;
            } else if (this.currentMode === 'draw') {
                // If user clicks on an existing box, switch to select mode
                if (opt.target && opt.target.type === 'rect') {
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

                const cls = this.classes.find(c => c.id === this.currentClassId) || { color: 'red' };

                this.rect = new fabric.Rect({
                    left: this.origX,
                    top: this.origY,
                    originX: 'left',
                    originY: 'top',
                    width: pointer.x - this.origX,
                    height: pointer.y - this.origY,
                    angle: 0,
                    fill: 'rgba(0,0,0,0)',
                    stroke: cls.color,
                    strokeWidth: 2 / this.getZoom(),
                    selectable: false, // temporarily false
                    classId: this.currentClassId
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
            } else if (this.isDrawing) {
                this.isDrawing = false;
                this.rect.setCoords();

                // If too small, remove
                if (this.rect.width < 5 || this.rect.height < 5) {
                    this.canvas.remove(this.rect);
                } else {
                    this.sortBoxesByArea();
                    // Auto-switch to select mode
                    this.setMode('select');
                    // Auto-select the new box
                    this.canvas.setActiveObject(this.rect);
                    this.onSelect({ selected: [this.rect] });
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
                    this.triggerGlowForClasses([targetClassId]);
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

        // Focus Mode Dimming Overlay
        this.canvas.on('after:render', (opt) => {
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
        });
    }

    onSelect(e) {
        const obj = e.selected[0];
        if (!obj || obj.type !== 'rect') return;

        this.renderMagnifier(obj);
        this.updateSelectionInfo(obj);
    }

    updateSelectionInfo(obj) {
        if (!obj) return;

        // Update Right Sidebar
        const clsName = this.classes.find(c => c.id === obj.classId)?.name || 'Unknown';
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

    onDeselect() {
        document.getElementById('selectionInfo').innerHTML = 'Nothing selected';
        document.getElementById('btnDeleteBox').style.display = 'none';

        const magCanvas = document.getElementById('magnifierCanvas');
        const magPlaceholder = document.getElementById('magPlaceholder');
        if (magCanvas) magCanvas.style.display = 'none';
        if (magPlaceholder) magPlaceholder.style.display = 'flex';

        // Also ensure rects are unselectable if in draw mode
        if (this.currentMode === 'draw') {
            this.canvas.forEachObject(o => o.selectable = false);
        }
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

            // Fabric coords (top-left) to Normalized Center
            const x_tl = obj.left;
            const y_tl = obj.top;
            const w = obj.width * obj.scaleX;
            const h = obj.height * obj.scaleY;

            const cx = (x_tl + w / 2) / this.imageWidth;
            const cy = (y_tl + h / 2) / this.imageHeight;
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

    toggleIsolateMode() {
        // Toggle Isolation
        this.isIsolationMode = !this.isIsolationMode;

        const activeObjects = this.canvas.getActiveObjects();

        this.canvas.getObjects().forEach(obj => {
            if (obj.type !== 'rect') return;

            if (this.isIsolationMode) {
                // Dim or hide others
                if (activeObjects.includes(obj)) {
                    obj.opacity = 1;
                    obj.selectable = true;
                    obj.evented = true;
                } else {
                    obj.opacity = 0.05; // Ghost them instead of full hide? User asked to "hide all... to see trash".
                    // User said "hide all... to look for trash" in prev request, but that was "Hide Image".
                    // Now user says "hide keys outside selected bbox".
                    // "ẩn tất cả bbox ngoài bbox đang được tôi chọn".
                    // So fully hide or extremely faint.
                    // Let's go with 0.1 opacity so user knows they exist but they don't clutter? 
                    // Or 0 (invisible). 
                    // "ẩn" implies invisible. But if invisible, user might create duplicate on top.
                    // Let's set opacity 0 for now as requested.
                    obj.opacity = 0;
                    obj.selectable = false;
                    obj.evented = false;
                }
            } else {
                // Restore All
                obj.opacity = 1;
                obj.selectable = true;
                obj.evented = true;
            }
        });

        this.canvas.requestRenderAll();

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
                        const sel = new fabric.ActiveSelection(newObjects, {
                            canvas: this.canvas,
                        });
                        this.canvas.setActiveObject(sel);
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
                    strokeWidth: 2 / this.getZoom() + extraStroke,
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
