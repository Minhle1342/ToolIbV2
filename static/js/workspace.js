// Initialized in workspace.html: const PROJECT_ID = ...

const editor = new Editor('c');
let currentImage = null;
let projectClasses = [];

class Workspace {
    constructor() {
        this.keysPressed = {};
        this.selectedImageIds = new Set();
        this.lastCheckedId = null;
        this.init();
        this.imageList = [];
    }

    async init() {
        // 1. Get Project Details (for classes)

        await this.loadProjectInfo();
        this.setupAutocomplete();
        this.setupImageSearchAutocomplete();
        await loadImages();
        this.updateSelectionUI();

        // Auto-select ACTIVE_FILENAME if set
        if (typeof ACTIVE_FILENAME !== 'undefined' && ACTIVE_FILENAME && currentWorkspace.allImages) {
            const matchedImg = currentWorkspace.allImages.find(img => img.filename === ACTIVE_FILENAME);
            if (matchedImg) {
                this.selectImage(matchedImg);
            }
        }

        // Hotkeys
        document.addEventListener('keyup', (e) => {
            this.keysPressed[e.key.toLowerCase()] = false;
        });
        window.addEventListener('blur', () => {
            this.keysPressed = {};
        });

        document.addEventListener('keydown', (e) => {
            // Ignore hotkeys if typing in an input text field
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                return;
            }

            const key = e.key.toLowerCase();
            this.keysPressed[key] = true;

            if (this.keysPressed['g'] && this.keysPressed['a']) {
                e.preventDefault();
                if (this.gTimeout) {
                    clearTimeout(this.gTimeout);
                    this.gTimeout = null;
                }
                this.toggleReviewAll();
                return;
            }

            // Supervised/Preview mode navigation with arrow keys
            if (this.isSupervisedMode && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
                e.preventDefault();
                if (e.key === 'ArrowLeft') {
                    this.prevSupervisedBox();
                } else {
                    this.nextSupervisedBox();
                }
                return;
            }

            // Tab / Shift+Tab: Cycle through bounding boxes
            if (e.key === 'Tab') {
                e.preventDefault();
                editor.selectNextBox(e.shiftKey);
                return;
            }

            if (e.key === 'Delete' || e.key === 'Backspace' || key === 'q') {
                editor.deleteSelected();
            }
            if (key === 's' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.save();
            }
            if (key === 'd' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                editor.duplicateSelected();
            } else if (key === 'd') {
                // Single D for Draw Mode
                editor.setMode('draw');
            }
            if (key === 'v') editor.setMode('select');
            if (key === 'r') editor.setMode('auto_label_region');
            if (key === 'f') this.toggleFlag();
            if (key === 'g') {
                this.gTimeout = setTimeout(() => {
                    this.toggleReview();
                }, 150);
            }
            if (key === 'l') this.toggleLockBox();
            if (key === 'h') this.toggleImageVisibility();
            if (key === 'i') this.toggleIsolateMode();
            if (key === 'a' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                editor.selectAllBoxes();
                return;
            }
            if (key === 'a') {
                if (!this.keysPressed['g']) {
                    editor.toggleStickyMove();
                }
            }

            // Class Hotkeys (0-9)
            if (e.key >= '0' && e.key <= '9') {
                const idx = parseInt(e.key);
                if (idx < projectClasses.length) {
                    const el = document.querySelectorAll('.class-item')[idx];
                    selectClass(idx, el);
                }
            }

            // Shortcuts Overlay
            if (e.key === '`' || e.key === '~') {
                e.preventDefault(); // Prevent typing `
                const modal = document.getElementById('shortcutsModal');
                if (modal) modal.classList.toggle('hidden');
            }
            if (e.key === 'Escape') {
                const modal = document.getElementById('shortcutsModal');
                if (modal && !modal.classList.contains('hidden')) {
                    modal.classList.add('hidden');
                    return; // Stop other esc actions if modal was open?
                }
            }

            // Undo/Redo
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
                e.preventDefault();
                if (e.shiftKey) {
                    editor.redo();
                } else {
                    editor.undo();
                }
            }
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
                e.preventDefault();
                editor.redo();
            }
        });


    }

    async loadProjectInfo() {
        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/classes`);
            projectClasses = await res.json();
            if (!projectClasses || projectClasses.length === 0) {
                // Fallback if empty or failed
                projectClasses = ['Class 0', 'Class 1', 'Class 2', 'Class 3', 'Class 4'];
            }
        } catch (e) {
            console.error(e);
            projectClasses = ['Error Loading Classes'];
        }
        this.renderClasses();
        this.renderClassFilters();
    }

    renderClasses() {
        const container = document.getElementById('classList');
        container.innerHTML = projectClasses.map((cls, idx) => `
            <div class="class-item px-4 py-3 cursor-pointer border-b border-border flex justify-between items-center text-sm hover:bg-panel transition-colors bg-surface text-content-muted group" 
                 onclick="selectClass(${idx}, this)" data-class-id="${idx}">
                <div class="flex items-center gap-3 overflow-hidden">
                     <div class="w-3 h-3 rounded-full shadow-sm flex-shrink-0" style="background-color: ${editor.colors[idx % 20]}"></div>
                     <span class="truncate group-hover:text-content transition-colors" title="${cls}">${cls}</span>
                </div>
                <span class="class-count-badge text-xs font-semibold px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 hidden" data-class-count-id="${idx}">0</span>
            </div>
        `).join('');
        editor.setClasses(projectClasses);
        updateClassListVisibility();
    }

    renderClassFilters() {
        const container = document.getElementById('classFilterContainer');
        if (!container) return;
        if (!projectClasses || projectClasses.length === 0) {
            container.innerHTML = '<span class="text-content-muted italic">No classes available</span>';
            return;
        }

        container.innerHTML = `
            <div class="flex items-center justify-between pb-1 mb-1 border-b border-border/50">
                <button type="button" class="text-[10px] text-primary hover:underline font-medium" onclick="currentWorkspace.toggleAllClassFilters(true)">Select All</button>
                <button type="button" class="text-[10px] text-content-muted hover:underline font-medium" onclick="currentWorkspace.toggleAllClassFilters(false)">Clear All</button>
            </div>
            <div class="space-y-1">
                ${projectClasses.map((cls, idx) => `
                    <div class="flex items-center justify-between group hover:bg-panel rounded px-1 -mx-1">
                        <label class="flex items-center gap-2 cursor-pointer hover:text-content text-content-muted transition-colors py-0.5 flex-1 min-w-0">
                            <input type="checkbox" value="${idx}" class="class-filter-checkbox rounded border-border bg-panel text-primary focus:ring-primary w-3.5 h-3.5" onchange="loadImages(false)">
                            <div class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background-color: ${editor.colors[idx % 20]}"></div>
                            <span class="truncate" title="${cls}">${cls}</span>
                        </label>
                        <button type="button" class="text-content-muted hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity p-1 ml-1 flex-shrink-0" onclick="currentWorkspace.deleteClass(${idx}, '${cls.replace(/'/g, "\\'")}')" title="Delete class">
                            <i class="fa-solid fa-trash text-[10px]"></i>
                        </button>
                    </div>
                `).join('')}
            </div>
        `;
    }

    toggleAllClassFilters(checked) {
        document.querySelectorAll('.class-filter-checkbox').forEach(cb => {
            cb.checked = checked;
        });
        loadImages(false);
    }

    async selectImage(image) {
        if (typeof editor !== 'undefined' && editor.isDirty) {
            const msg = typeof window.t === 'function' ? window.t('unsaved_changes_warning') : 'Vui lòng lưu thay đổi trước khi chuyển sang ảnh khác!';
            alert(msg);
            return;
        }

        // Reset supervised mode when switching image
        this.isSupervisedMode = false;
        this.updateSupervisedUI();

        currentImage = image;
        if (typeof window.updateMyImageId === 'function') {
            window.updateMyImageId(image.id);
        }

        // Update URL
        if (window.history && window.history.pushState) {
            window.history.pushState(null, '', `/project/${PROJECT_ID}/${encodeURIComponent(image.filename)}`);
        }

        // Update Split Type Select
        const select = document.getElementById('splitTypeSelect');
        if (select) {
            if (image.split_type) {
                select.value = image.split_type;
                let colorClasses = 'bg-gray-500/20 text-gray-400 border-gray-500/30';
                if (image.split_type === 'train') colorClasses = 'bg-blue-500/20 text-blue-400 border-blue-500/30';
                else if (image.split_type === 'val') colorClasses = 'bg-green-500/20 text-green-400 border-green-500/30';
                else if (image.split_type === 'test') colorClasses = 'bg-purple-500/20 text-purple-400 border-purple-500/30';

                select.className = `absolute top-4 right-4 px-3 py-1 pr-6 text-xs font-bold rounded-md shadow z-10 backdrop-blur-sm uppercase tracking-wider border cursor-pointer outline-none hover:opacity-80 transition-opacity ${colorClasses}`;
            } else {
                select.className = 'hidden';
            }
        }

        // Update Active Item in List
        document.querySelectorAll('.image-item').forEach(el => {
            el.classList.remove('bg-blue-600/30', 'border-l-4', 'border-blue-500', 'text-white', 'font-semibold', 'bg-panel', 'border-l-2', 'border-primary', 'text-primary');
            el.classList.add('bg-surface', 'text-content-muted', 'border-l-0', 'border-transparent');
        });
        const el = document.getElementById(`img-${image.id}`);
        if (el) {
            el.classList.remove('bg-surface', 'text-content-muted', 'border-l-0', 'border-transparent');
            el.classList.add('bg-blue-600/30', 'border-l-4', 'border-blue-500', 'text-white', 'font-semibold');
        }

        // Show scroll-to-active button
        const scrollBtn = document.getElementById('btnScrollToActive');
        if (scrollBtn) scrollBtn.classList.remove('hidden');

        // Update Flag Button
        this.updateFlagButton();
        this.updateReviewButton();
        this.renderImageTags();

        // Load into Canvas
        // Image URL: We need a route to serve the raw image.
        // Does Flask `static` serve the root_path? No.
        // We need a route `/api/serve_image/<id>`?
        // Or just serve from a symlink?
        // Best approach: Add endpoint in `routes.py` to serve image bytes.

        // I will add `/api/image_data/<id>` in routes.
        const url = `/api/image_data/${image.id}`;

        // For Image Size, we let Fabric load it.
        // But we need to know size for YOLO conversion? Fabric keeps track.

        // Wait, Fabric Image.fromURL loads the image.
        editor.canvas.clear();
        editor.loading = true;

        // Increment load sequence to guard against stale callbacks
        const loadSeq = ++editor._loadSequence;

        // 1. Get Labels first?
        const labels = await API.getLabel(image.id);

        // Check if user already switched to another image
        if (loadSeq !== editor._loadSequence) return;

        // 2. Load Image
        // We need to fetch image dimensions first or let Fabric handle it.
        // Fabric handles it.

        fabric.Image.fromURL(url, (img) => {
            // GUARD: If the user clicked another image while this was loading, discard
            if (loadSeq !== editor._loadSequence) return;

            if (!img) {
                editor.loading = false;
                alert('Failed to load image');
                return;
            }

            if (image.overlapThreshold !== undefined && image.overlapThreshold !== null) {
                for (let i = 0; i < labels.length; i++) {
                    labels[i].isOverlapping = false;
                }
                for (let i = 0; i < labels.length; i++) {
                    for (let j = i + 1; j < labels.length; j++) {
                        const iou = calculateIoU(labels[i], labels[j]);
                        if (iou >= image.overlapThreshold) {
                            labels[i].isOverlapping = true;
                            labels[j].isOverlapping = true;
                        }
                    }
                }
            }

            editor.loadImage(img);
            editor.loadBoxes(labels);

            if (typeof window.collabSocket !== 'undefined' && window.collabSocket && window.collabSocket.connected) {
                window.collabSocket.emit('request_sync', { image_id: image.id });
            }

            // Trigger visual glow effect for active class filters
            const checkboxes = document.querySelectorAll('.class-filter-checkbox');
            const selectedClasses = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => parseInt(cb.value));

            editor.triggerGlowForClasses(selectedClasses);

            // Update Inspection View with Image Metadata
            this.updateImageStats(img, labels.length);
            editor.loading = false;
        });
    }

    scrollToActiveImage() {
        if (!currentImage) return;
        const el = document.getElementById(`img-${currentImage.id}`);
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    updateImageStats(img, boxCount) {
        const magCanvas = document.getElementById('magnifierCanvas');
        const magPlaceholder = document.getElementById('magPlaceholder');
        if (magCanvas) magCanvas.style.display = 'none';
        if (magPlaceholder) {
            magPlaceholder.style.display = 'flex';
            magPlaceholder.querySelector('span').textContent = 'Select a box to zoom';
        }

        document.getElementById('selectionInfo').innerHTML = `
            <div class="mb-2">
                <div class="flex justify-between items-center">
                    <div>
                        <label class="block text-xs text-gray-500 mb-0.5 uppercase tracking-wider">Resolution</label>
                        <span class="text-sm font-medium text-gray-300 font-mono">${img.width} x ${img.height}</span>
                    </div>
                    <button class="p-1.5 text-red-400 hover:text-white hover:bg-red-600 rounded transition-colors"
                        onclick="currentWorkspace.deleteImage()" title="Delete Image">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            </div>
            <div class="mb-2">
                <label class="block text-xs text-gray-500 mb-0.5 uppercase tracking-wider">Total Boxes</label>
                <span class="text-sm font-medium text-gray-300 font-mono">${boxCount}</span>
            </div>
            <p class="text-xs text-gray-600 mt-2 italic">Select a box for details</p>
        `;
    }

    async deleteImage() {
        if (!currentImage) return;

        if (!confirm('Are you sure you want to delete this image? This action cannot be undone.')) {
            return;
        }

        try {
            const res = await API.deleteImage(currentImage.id);
            if (res.message || res.success) {
                const currentIndex = this.allImages.findIndex(img => img.id === currentImage.id);
                if (currentIndex !== -1) {
                    this.allImages.splice(currentIndex, 1);
                }

                await loadImages(false);

                if (this.allImages.length > 0) {
                    const nextIndex = Math.min(currentIndex, this.allImages.length - 1);
                    await this.selectImage(this.allImages[nextIndex]);
                } else {
                    currentImage = null;
                    if (editor) editor.clearCanvas();
                    document.getElementById('selectionInfo').innerHTML = 'No images left';
                }
            } else {
                alert(res.error || 'Failed to delete image');
            }
        } catch (e) {
            console.error('Delete error:', e);
            alert('Failed to delete image: ' + e.message);
        }
    }

    deleteCurrentImage() {
        this.deleteImage();
    }

    handleCheckboxClick(event, imgId) {
        const isChecked = event.target.checked;

        if (event.shiftKey && this.lastCheckedId !== null) {
            const idx1 = this.imageList.findIndex(img => img.id === this.lastCheckedId);
            const idx2 = this.imageList.findIndex(img => img.id === imgId);

            if (idx1 !== -1 && idx2 !== -1) {
                const minIdx = Math.min(idx1, idx2);
                const maxIdx = Math.max(idx1, idx2);

                for (let i = minIdx; i <= maxIdx; i++) {
                    const img = this.imageList[i];
                    if (isChecked) {
                        this.selectedImageIds.add(img.id);
                    } else {
                        this.selectedImageIds.delete(img.id);
                    }

                    const cb = document.querySelector(`.image-checkbox[data-id="${img.id}"]`);
                    if (cb) {
                        cb.checked = isChecked;
                    }
                }
                this.lastCheckedId = imgId;
                this.updateSelectionUI();
                return;
            }
        }

        if (isChecked) {
            this.selectedImageIds.add(imgId);
        } else {
            this.selectedImageIds.delete(imgId);
        }
        this.lastCheckedId = imgId;
        this.updateSelectionUI();
    }

    updateSelectionUI() {
        const count = this.selectedImageIds.size;
        const selectedCountEl = document.getElementById('selectedCount');
        if (selectedCountEl) {
            selectedCountEl.innerText = count;
        }

        const btnDeleteSelected = document.getElementById('btnDeleteSelected');
        if (btnDeleteSelected) {
            if (count > 0) {
                btnDeleteSelected.disabled = false;
                btnDeleteSelected.classList.remove('opacity-50', 'cursor-not-allowed');
            } else {
                btnDeleteSelected.disabled = true;
                btnDeleteSelected.classList.add('opacity-50', 'cursor-not-allowed');
            }
        }

        const btnClearSelection = document.getElementById('btnClearSelection');
        if (btnClearSelection) {
            if (count > 0) {
                btnClearSelection.classList.remove('hidden');
            } else {
                btnClearSelection.classList.add('hidden');
            }
        }

        const batchActionPanel = document.getElementById('batchActionPanel');
        if (batchActionPanel) {
            if (count > 0) {
                batchActionPanel.classList.remove('hidden');
            } else {
                batchActionPanel.classList.add('hidden');
            }
        }
    }

    clearImageSelection() {
        this.selectedImageIds.clear();
        this.lastCheckedId = null;
        document.querySelectorAll('.image-checkbox').forEach(cb => {
            cb.checked = false;
        });
        this.updateSelectionUI();
    }

    async deleteSelectedImages() {
        const imageIds = Array.from(this.selectedImageIds);
        if (imageIds.length === 0) return;

        if (!confirm(`Bạn có chắc chắn muốn xóa ${imageIds.length} ảnh đã chọn không? Hành động này không thể hoàn tác.`)) {
            return;
        }

        try {
            const res = await API.batchDeleteImages({ image_ids: imageIds });
            if (res.message || res.success) {
                const currentImageDeleted = this.selectedImageIds.has(currentImage ? currentImage.id : null);

                let nextImageToSelect = null;
                if (currentImageDeleted && currentImage) {
                    const currentIndex = this.imageList.findIndex(img => img.id === currentImage.id);
                    const remainingListed = this.imageList.filter(img => !this.selectedImageIds.has(img.id));
                    if (remainingListed.length > 0) {
                        const nextIndex = Math.min(currentIndex, remainingListed.length - 1);
                        nextImageToSelect = remainingListed[nextIndex];
                    }
                }

                // Remove from allImages
                this.allImages = this.allImages.filter(img => !this.selectedImageIds.has(img.id));

                // Clear selection
                this.selectedImageIds.clear();
                this.lastCheckedId = null;
                this.updateSelectionUI();

                // Reload list
                await loadImages(false);

                // Select next available image if needed
                if (currentImageDeleted) {
                    if (nextImageToSelect) {
                        await this.selectImage(nextImageToSelect);
                    } else if (this.imageList.length > 0) {
                        await this.selectImage(this.imageList[0]);
                    } else {
                        currentImage = null;
                        if (editor) editor.clearCanvas();
                        document.getElementById('selectionInfo').innerHTML = 'No images left';
                    }
                }
            } else {
                alert(res.error || 'Failed to delete selected images');
            }
        } catch (e) {
            console.error('Batch delete error:', e);
            alert('Failed to delete: ' + e.message);
        }
    }

    async deleteListedImages() {
        const imageIds = this.imageList.map(img => img.id);
        if (imageIds.length === 0) {
            alert('Không có ảnh nào trong danh sách hiện tại để xóa.');
            return;
        }

        if (!confirm(`Bạn có chắc chắn muốn xóa TẤT CẢ ${imageIds.length} ảnh trong danh sách hiện tại không? Hành động này không thể hoàn tác.`)) {
            return;
        }

        try {
            const res = await API.batchDeleteImages({ image_ids: imageIds });
            if (res.message || res.success) {
                const currentImageDeleted = imageIds.includes(currentImage ? currentImage.id : null);

                // Remove from allImages
                const deletedSet = new Set(imageIds);
                this.allImages = this.allImages.filter(img => !deletedSet.has(img.id));

                // Also remove deleted IDs from selectedImageIds if any were selected
                imageIds.forEach(id => this.selectedImageIds.delete(id));
                if (this.lastCheckedId && deletedSet.has(this.lastCheckedId)) {
                    this.lastCheckedId = null;
                }
                this.updateSelectionUI();

                // Reload list
                await loadImages(false);

                // If current image was deleted, select the first remaining listed image (if any)
                if (currentImageDeleted) {
                    if (this.imageList.length > 0) {
                        await this.selectImage(this.imageList[0]);
                    } else {
                        currentImage = null;
                        if (editor) editor.clearCanvas();
                        document.getElementById('selectionInfo').innerHTML = 'No images left';
                    }
                }
            } else {
                alert(res.error || 'Failed to delete listed images');
            }
        } catch (e) {
            console.error('Batch delete error:', e);
            alert('Failed to delete: ' + e.message);
        }
    }

    toggleFlag() {
        if (!currentImage) return;
        currentImage.flag_status = (currentImage.flag_status === 'Flagged') ? 'Normal' : 'Flagged';
        this.updateFlagButton();
        this.save(true); // Auto save status

        // Update list icon
        const el = document.getElementById(`img-${currentImage.id}`);
        if (el) {
            // Re-render essentially or just toggle icon class? Easier to just reload list or toggle specific classes?
            // Since we use Tailwind, "flagged" class isn't defined. We must update DOM manually or re-render.
            // Let's just find the flag icon and toggle it.
            const iconContainer = el.querySelector('.flex.items-center.gap-2');
            if (currentImage.flag_status === 'Flagged') {
                if (!iconContainer.querySelector('.fa-flag')) {
                    iconContainer.insertAdjacentHTML('afterbegin', '<i class="fa-solid fa-flag text-red-500"></i>');
                }
            } else {
                const flag = iconContainer.querySelector('.fa-flag');
                if (flag) flag.remove();
            }
        }
    }

    updateFlagButton() {
        const btn = document.getElementById('btnFlag');
        if (currentImage.flag_status === 'Flagged') {
            btn.classList.add('text-red-500');
            btn.classList.remove('text-content-muted');
        } else {
            btn.classList.remove('text-red-500');
            btn.classList.add('text-content-muted');
        }
    }

    toggleReview() {
        if (!currentImage) return;
        currentImage.is_reviewed = !currentImage.is_reviewed;
        this.updateReviewButton();
        this.save(true);

        // Update list icon
        const el = document.getElementById(`img-${currentImage.id}`);
        if (el) {
            const iconContainer = el.querySelector('.flex.items-center.gap-2');
            if (currentImage.is_reviewed) {
                if (!iconContainer.querySelector('.fa-circle-check')) {
                    iconContainer.insertAdjacentHTML('afterbegin', '<i class="fa-solid fa-circle-check text-green-500"></i>');
                }
            } else {
                const icon = iconContainer.querySelector('.fa-circle-check');
                if (icon) icon.remove();
            }
        }

        // Update allImages cache
        if (this.allImages) {
            const localImg = this.allImages.find(i => i.id === currentImage.id);
            if (localImg) localImg.is_reviewed = currentImage.is_reviewed;
        }
    }

    async toggleReviewAll() {
        if (!this.imageList || this.imageList.length === 0) return;

        // Check if there is at least one unreviewed image in the list
        const hasUnreviewed = this.imageList.some(img => !img.is_reviewed);
        const targetReviewed = hasUnreviewed; // if has unreviewed, mark all as reviewed; else mark all as unreviewed

        const imageIds = this.imageList.map(img => img.id);

        try {
            const res = await API.batchReview({
                image_ids: imageIds,
                is_reviewed: targetReviewed
            });

            if (res.message) {
                // Update local states
                this.imageList.forEach(img => {
                    img.is_reviewed = targetReviewed;
                });
                if (this.allImages) {
                    this.allImages.forEach(img => {
                        if (imageIds.includes(img.id)) {
                            img.is_reviewed = targetReviewed;
                        }
                    });
                }

                // If currentImage is in the updated list, update its state and the UI button
                if (currentImage && imageIds.includes(currentImage.id)) {
                    currentImage.is_reviewed = targetReviewed;
                    this.updateReviewButton();
                }

                // Update the sidebar icons in the DOM
                imageIds.forEach(id => {
                    const el = document.getElementById(`img-${id}`);
                    if (el) {
                        const iconContainer = el.querySelector('.flex.items-center.gap-2');
                        if (iconContainer) {
                            const icon = iconContainer.querySelector('.fa-circle-check');
                            if (targetReviewed) {
                                if (!icon) {
                                    iconContainer.insertAdjacentHTML('afterbegin', '<i class="fa-solid fa-circle-check text-green-500"></i>');
                                }
                            } else {
                                if (icon) icon.remove();
                            }
                        }
                    }
                });

                this.showToast(targetReviewed ? 'Marked all as reviewed' : 'Unmarked all reviews', 'success');
            } else {
                alert(res.error || 'Failed to update review status');
            }
        } catch (e) {
            console.error('Batch review error:', e);
            alert('Failed to update review status: ' + e.message);
        }
    }

    updateReviewButton() {
        const btn = document.getElementById('btnReview');
        if (!btn) return;
        if (currentImage && currentImage.is_reviewed) {
            btn.classList.add('text-green-500');
            btn.classList.remove('text-content-muted');
            btn.querySelector('i').className = 'fa-solid fa-circle-check text-lg';
        } else {
            btn.classList.remove('text-green-500');
            btn.classList.add('text-content-muted');
            btn.querySelector('i').className = 'fa-regular fa-circle-check text-lg';
        }
    }

    toggleLockBox() {
        if (typeof editor !== 'undefined') editor.toggleLockBox();
    }

    toggleImageVisibility() {
        if (typeof editor !== 'undefined') editor.toggleImageVisibility();
    }

    toggleIsolateMode() {
        if (typeof editor !== 'undefined') editor.toggleIsolateMode();
    }

    setSequenceMode(mode) {
        if (typeof editor !== 'undefined') {
            const active = editor.setSequenceMode(mode);
            const btn = document.getElementById('btnShowSequenceNumbers');
            if (btn) {
                if (active) {
                    btn.classList.add('text-blue-500');
                    btn.classList.remove('text-content-muted');
                } else {
                    btn.classList.remove('text-blue-500');
                    btn.classList.add('text-content-muted');
                }
            }
            if (typeof updateClassListVisibility === 'function') {
                updateClassListVisibility();
            }
        }
    }

    toggleBoxesVisibility() {
        if (typeof editor !== 'undefined') {
            const active = editor.toggleBoxesVisibility();
            const btn = document.getElementById('btnHideBoxes');
            if (btn) {
                const icon = btn.querySelector('i');
                if (!active) {
                    btn.classList.add('text-red-500');
                    btn.classList.remove('text-content-muted');
                    if (icon) {
                        icon.className = 'fa-solid fa-eye-slash text-lg';
                    }
                } else {
                    btn.classList.remove('text-red-500');
                    btn.classList.add('text-content-muted');
                    if (icon) {
                        icon.className = 'fa-solid fa-eye text-lg';
                    }
                }
            }
        }
    }

    async loadProjectTags() {
        if (!this.projectTags) {
            try {
                const res = await fetch(`/api/projects/${PROJECT_ID}/tags`);
                if (res.ok) {
                    this.projectTags = await res.json();
                } else {
                    this.projectTags = [];
                }
            } catch (e) {
                console.error("Failed to load tags", e);
                this.projectTags = [];
            }
        }
        return this.projectTags;
    }

    async openTagManager() {
        window.location.href = `/project/${PROJECT_ID}/tags`;
    }

    renderTagManagerList() {
        const container = document.getElementById('tagManagerList');
        if (!this.projectTags || this.projectTags.length === 0) {
            container.innerHTML = '<div class="text-sm text-content-muted p-2" data-i18n="no_tags">No tags available.</div>';
            return;
        }
        container.innerHTML = this.projectTags.map(tag => `
            <div class="flex items-center justify-between p-2 hover:bg-panel rounded border border-transparent hover:border-border transition-colors group">
                <div class="flex items-center gap-2 flex-1">
                    <input type="color" value="${tag.color}" class="w-6 h-6 rounded cursor-pointer border-none p-0" onchange="currentWorkspace.updateTagColor(${tag.id}, this.value)">
                    <span class="text-sm text-content flex-1">${tag.name}</span>
                </div>
                <button type="button" class="text-content-muted hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity p-1 ml-2" onclick="currentWorkspace.deleteTag(${tag.id})" title="Delete tag">
                    <i class="fa-solid fa-trash text-xs"></i>
                </button>
            </div>
        `).join('');
    }

    async addTag() {
        const nameInput = document.getElementById('newTagName');
        const colorInput = document.getElementById('newTagColor');
        const name = nameInput.value.trim();
        const color = colorInput.value;

        if (!name) return;

        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/tags`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, color })
            });
            const data = await res.json();
            if (res.ok) {
                this.projectTags.push(data);
                this.renderTagManagerList();
                nameInput.value = '';
            } else {
                alert(data.error || 'Failed to add tag');
            }
        } catch (e) {
            console.error('Add tag error:', e);
            alert('Failed to add tag');
        }
    }

    async deleteTag(tagId) {
        if (!confirm('Are you sure you want to delete this tag?')) return;
        try {
            const res = await fetch(`/api/tags/${tagId}`, { method: 'DELETE' });
            if (res.ok) {
                this.projectTags = this.projectTags.filter(t => t.id !== tagId);
                this.renderTagManagerList();
                if (currentImage && currentImage.tags) {
                    currentImage.tags = currentImage.tags.filter(t => t.id !== tagId);
                    this.renderImageTags();
                }
            } else {
                const data = await res.json();
                alert(data.error || 'Failed to delete tag');
            }
        } catch (e) {
            console.error('Delete tag error:', e);
            alert('Failed to delete tag');
        }
    }

    async updateTagColor(tagId, newColor) {
        try {
            const res = await fetch(`/api/tags/${tagId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ color: newColor })
            });
            if (res.ok) {
                const data = await res.json();
                const tag = this.projectTags.find(t => t.id === tagId);
                if (tag) tag.color = data.color;
                if (currentImage && currentImage.tags) {
                    const imgTag = currentImage.tags.find(t => t.id === tagId);
                    if (imgTag) imgTag.color = data.color;
                    this.renderImageTags();
                }
            }
        } catch (e) {
            console.error('Update tag error:', e);
        }
    }

    async openTagSelector() {
        if (!currentImage) return;
        await this.loadProjectTags();
        const container = document.getElementById('tagSelectorList');
        if (!this.projectTags || this.projectTags.length === 0) {
            container.innerHTML = '<div class="text-sm text-content-muted p-2">No tags available. Go to Tag Manager to create some.</div>';
        } else {
            const currentTagIds = (currentImage.tags || []).map(t => t.id);
            container.innerHTML = this.projectTags.map(tag => `
                <label class="flex items-center space-x-2 text-sm text-content hover:bg-panel p-2 rounded cursor-pointer border border-transparent hover:border-border transition-colors">
                    <input type="checkbox" name="imageTag" value="${tag.id}" ${currentTagIds.includes(tag.id) ? 'checked' : ''} class="form-checkbox h-4 w-4 text-primary rounded border-border bg-surface focus:ring-primary focus:ring-offset-panel">
                    <span class="w-3 h-3 rounded-full flex-shrink-0" style="background-color: ${tag.color}"></span>
                    <span class="flex-grow">${tag.name}</span>
                </label>
            `).join('');
        }
        document.getElementById('tagSelectorModal').classList.remove('hidden');
    }

    async saveImageTags() {
        if (!currentImage) return;
        const checkedBoxes = Array.from(document.querySelectorAll('input[name="imageTag"]:checked'));
        const tagIds = checkedBoxes.map(cb => parseInt(cb.value));

        try {
            const res = await fetch(`/api/images/${currentImage.id}/tags`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tag_ids: tagIds })
            });
            if (res.ok) {
                const data = await res.json();
                currentImage.tags = data.tags;
                this.renderImageTags();

                const listImg = this.allImages.find(img => img.id === currentImage.id);
                if (listImg) listImg.tags = data.tags;

                if (typeof closeModal === 'function') {
                    closeModal('tagSelectorModal');
                }
            } else {
                const data = await res.json();
                alert(data.error || 'Failed to save tags');
            }
        } catch (e) {
            console.error('Save tags error:', e);
            alert('Failed to save tags');
        }
    }

    renderImageTags() {
        const container = document.getElementById('currentImageTags');
        if (!container) return;
        if (!currentImage || !currentImage.tags || currentImage.tags.length === 0) {
            container.innerHTML = '<span class="text-xs text-content-muted italic" data-i18n="no_tags_assigned">No tags assigned</span>';
            return;
        }
        container.innerHTML = currentImage.tags.map(tag => `
            <span class="text-xs px-2 py-0.5 rounded-full flex items-center gap-1.5" style="background-color: ${tag.color}20; color: ${tag.color}; border: 1px solid ${tag.color}40;">
                <span class="w-1.5 h-1.5 rounded-full" style="background-color: ${tag.color}"></span>
                ${tag.name}
            </span>
        `).join('');
    }

    async save(silent = false) {
        if (!currentImage) return;

        const btn = document.querySelector('button[onclick="currentWorkspace.save()"]');
        const btnSpan = document.getElementById('btnSavedText');

        let originalText = btnSpan ? btnSpan.textContent : 'Saved';
        let originalI18n = btnSpan ? btnSpan.getAttribute('data-i18n') : 'btn_saved';
        let originalClasses = 'bg-primary hover:bg-blue-500 text-content-inv text-sm font-medium px-4 py-1.5 rounded ml-2';
        if (btn) {
            originalClasses = btn.className;
        }

        try {
            if (silent && btnSpan && btn) {
                btnSpan.setAttribute('data-i18n', 'btn_saving');
                btnSpan.textContent = typeof window.t === 'function' ? window.t('btn_saving') : 'Saving...';
                btn.className = 'bg-primary/70 text-content-inv text-sm font-medium px-4 py-1.5 rounded ml-2 cursor-wait';
            }

            const boxes = editor.getBoxesYOLO();

            const data = {
                image_id: currentImage.id,
                labels: boxes,
                flag_status: currentImage.flag_status,
                split_type: currentImage.split_type,
                is_reviewed: currentImage.is_reviewed || false,
                save_time: Date.now()
            };

            const result = await API.saveLabel(data);

            if (result.ignored) {
                if (!silent) {
                    alert('Another user has already saved a newer version of this image. Your save was ignored to prevent overwriting newer data.');
                }
                return;
            }

            if (typeof editor !== 'undefined') {
                editor.isDirty = false;
            }

            // Update local classes cache for filtering and checkmark status
            if (currentWorkspace.allImages) {
                const localImg = currentWorkspace.allImages.find(i => i.id === currentImage.id);
                if (localImg) {
                    const uniqueClasses = Array.from(new Set(boxes.map(b => b.class_id))).sort((a, b) => a - b);
                    localImg.classes = uniqueClasses;
                    localImg.is_labeled = boxes.length > 0;

                    // Update check icon in DOM without reloading the whole list
                    const el = document.getElementById(`img-${currentImage.id}`);
                    if (el) {
                        const iconContainer = el.querySelector('.flex.items-center.gap-2');
                        if (iconContainer) {
                            let checkIcon = iconContainer.querySelector('.fa-check') || iconContainer.querySelector('.fa-circle');
                            if (!checkIcon) {
                                iconContainer.insertAdjacentHTML('beforeend', '<i class="fa-regular fa-circle text-content-muted"></i>');
                                checkIcon = iconContainer.querySelector('.fa-circle');
                            }
                            if (checkIcon) {
                                if (boxes.length > 0) {
                                    checkIcon.className = 'fa-solid fa-check text-secondary';
                                } else {
                                    checkIcon.className = 'fa-regular fa-circle text-content-muted';
                                }
                            }
                        }
                    }
                }
            }

            if (window.collabSocket && window.collabSocket.connected) {
                const uniqueClasses = Array.from(new Set(boxes.map(b => b.class_id))).sort((a, b) => a - b);
                window.collabSocket.emit('notify_annotations_changed', {
                    project_id: typeof PROJECT_ID !== 'undefined' ? PROJECT_ID : null,
                    image_id: currentImage.id,
                    user_name: localStorage.getItem('collab_username') || 'Someone',
                    is_labeled: boxes.length > 0,
                    classes: uniqueClasses
                });
            }

            if (btnSpan && btn) {
                if (silent) {
                    btnSpan.setAttribute('data-i18n', originalI18n);
                    btnSpan.textContent = originalText;
                    btn.className = originalClasses;
                } else {
                    btnSpan.textContent = 'Success!';
                    btn.className = 'bg-green-500 hover:bg-green-600 text-white text-sm font-medium px-4 py-1.5 rounded ml-2';
                    setTimeout(() => {
                        btnSpan.setAttribute('data-i18n', originalI18n);
                        btnSpan.textContent = originalText;
                        btn.className = originalClasses;
                    }, 1000);
                }
            }
        } catch (error) {
            console.error('Save error:', error);
            if (btnSpan && btn) {
                btnSpan.textContent = 'Failed!';
                btn.className = 'bg-red-500 hover:bg-red-600 text-white text-sm font-medium px-4 py-1.5 rounded ml-2';
                setTimeout(() => {
                    btnSpan.setAttribute('data-i18n', originalI18n);
                    btnSpan.textContent = originalText;
                    btn.className = originalClasses;
                }, 1000);
            }
            if (!silent) {
                alert('Save failed: ' + (error.message || 'Unknown error'));
            }
        }
    }



    async collectCrop() {
        if (!currentImage) return;

        const selectedBoxes = editor.getSelectedBoxesInfo();
        if (!selectedBoxes || selectedBoxes.length === 0) {
            alert('Please select a bounding box first.');
            return;
        }

        const btn = document.getElementById('btnCollectCrop');
        let originalHtml = '';
        if (btn) {
            originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Collecting...';
            btn.disabled = true;
        }

        try {
            if (selectedBoxes.length === 1) {
                // Single box — use single API for detailed feedback
                const boxInfo = selectedBoxes[0];
                const result = await API.collectCrop({
                    image_id: currentImage.id,
                    box: { x: boxInfo.x, y: boxInfo.y, w: boxInfo.w, h: boxInfo.h },
                    class_name: boxInfo.class_name
                });

                if (result.success) {
                    this.showToast(`Collected: ${result.class_name} (total: ${result.total_class_crops})`, 'success');
                } else {
                    alert(result.error || 'Failed to collect crop');
                }
            } else {
                // Multiple boxes — use batch API
                const result = await API.collectCropBatch({
                    image_id: currentImage.id,
                    boxes: selectedBoxes
                });

                if (result.success) {
                    this.showToast(`Collected ${result.collected}/${result.total_boxes} selected crops`, 'success');
                } else {
                    alert(result.error || 'Failed to collect crops');
                }
            }

            if (btn) {
                btn.innerHTML = '<i class="fa-solid fa-check"></i> Collected!';
                btn.classList.add('bg-green-600');
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.classList.remove('bg-green-600');
                    btn.disabled = false;
                }, 1200);
            }
        } catch (e) {
            alert('Error: ' + e.message);
            if (btn) { btn.innerHTML = originalHtml; btn.disabled = false; }
        }
    }

    async classifySelectedBoxes() {
        if (!currentImage) return;

        const selectedBoxes = editor.getSelectedBoxesInfo();
        if (!selectedBoxes || selectedBoxes.length === 0) {
            alert('Please select a bounding box first.');
            return;
        }

        const btn = document.getElementById('btnClassifySelected');
        let originalHtml = '';
        if (btn) {
            originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Classifying...';
            btn.disabled = true;
        }

        try {
            const result = await API.classifyBoxes({
                image_id: currentImage.id,
                boxes: selectedBoxes
            });

            if (result.success) {
                editor.updateActiveBoxesClasses(result.results);
                this.showToast(`Classified ${selectedBoxes.length} box(es)`, 'success');
                this.save(true);

                if (btn) {
                    btn.innerHTML = '<i class="fa-solid fa-check"></i> Classified!';
                    btn.classList.add('bg-green-600');
                    setTimeout(() => {
                        btn.innerHTML = originalHtml;
                        btn.classList.remove('bg-green-600');
                        btn.disabled = false;
                    }, 1200);
                }
            } else {
                alert(result.error || 'Failed to classify boxes');
                if (btn) { btn.innerHTML = originalHtml; btn.disabled = false; }
            }
        } catch (e) {
            alert('Error: ' + e.message);
            if (btn) { btn.innerHTML = originalHtml; btn.disabled = false; }
        }
    }

    async collectAllBoxes() {
        if (!currentImage) return;

        const boxes = editor.getAllBoxesWithClassNames();
        if (!boxes || boxes.length === 0) {
            alert('No bounding boxes on current image.');
            return;
        }

        if (!confirm(`Collect crops for all ${boxes.length} boxes on this image?`)) {
            return;
        }

        const btn = document.getElementById('btnCollectAll');
        let originalHtml = '';
        if (btn) {
            originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            btn.disabled = true;
        }

        try {
            const result = await API.collectCropBatch({
                image_id: currentImage.id,
                boxes: boxes
            });

            if (result.success) {
                this.showToast(`Collected ${result.collected}/${result.total_boxes} crops`, 'success');
            } else {
                alert(result.error || 'Failed to collect crops');
            }
        } catch (e) {
            alert('Error: ' + e.message);
        } finally {
            if (btn) { btn.innerHTML = originalHtml; btn.disabled = false; }
        }
    }

    showToast(message, type = 'info') {
        // Create a floating toast notification
        const toast = document.createElement('div');
        const bgColor = type === 'success' ? 'bg-green-600' : type === 'error' ? 'bg-red-600' : 'bg-blue-600';
        toast.className = `fixed bottom-6 left-1/2 -translate-x-1/2 ${bgColor} text-white px-5 py-2.5 rounded-lg shadow-2xl text-sm font-medium z-[9999] transition-all duration-300 flex items-center gap-2`;

        const icon = type === 'success' ? 'fa-circle-check' : type === 'error' ? 'fa-circle-xmark' : 'fa-circle-info';
        toast.innerHTML = `<i class="fa-solid ${icon}"></i> ${message}`;

        document.body.appendChild(toast);

        // Animate in
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-50%) translateY(20px)';
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(-50%) translateY(0)';
        });

        // Auto remove after 3s
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(-50%) translateY(20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    async autoLabel() {
        if (!currentImage) return;

        const btn = document.getElementById('btnAutoLabelToggle');
        if (!btn) return;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;

        if (typeof editor !== 'undefined') {
            editor.clearAllBoxes();
        }

        try {
            const data = await API.autoLabel(currentImage.id);
            if (data.success) {
                if (data.boxes.length > 0) {
                    editor.loadBoxes(data.boxes);
                }
            }
        } catch (e) {
            alert(e.message);
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }

    async startSupervisedLabeling() {
        if (!currentImage) return;

        const btn = document.getElementById('btnAutoLabelToggle');
        if (!btn) return;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;

        if (typeof editor !== 'undefined') {
            editor.clearAllBoxes();
        }

        try {
            const data = await API.autoLabel(currentImage.id);
            if (data.success) {
                if (data.boxes.length > 0) {
                    editor.loadBoxes(data.boxes);
                    this.isSupervisedMode = true;
                    this.updateSupervisedUI();

                    setTimeout(() => {
                        editor.canvas.discardActiveObject();
                        editor.selectNextBox(false);
                        this.zoomToActiveBox();
                        if (typeof editor !== 'undefined' && !editor.isIsolationMode) {
                            editor.isIsolationMode = true;
                            editor.updateIsolateView();

                            const btnIsolate = document.getElementById('btnIsolate');
                            if (btnIsolate) {
                                btnIsolate.classList.add('text-yellow-500');
                                btnIsolate.classList.remove('text-gray-400');
                            }
                        }
                        this.updateSupervisedUI();
                    }, 100);
                } else {
                    this.showToast('No objects detected.', 'info');
                }
            }
        } catch (e) {
            alert(e.message);
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }

    startPreviewBoxes() {
        if (!currentImage || typeof editor === 'undefined' || !editor.canvas) return;

        const boxes = editor.canvas.getObjects('rect');
        if (boxes.length === 0) {
            this.showToast(typeof window.t === 'function' ? window.t('no_boxes_preview') || 'No boxes to preview' : 'No boxes to preview', 'info');
            return;
        }

        this.isSupervisedMode = true;
        this.updateSupervisedUI();

        setTimeout(() => {
            const activeObj = editor.canvas.getActiveObject();
            if (!activeObj || activeObj.type !== 'rect') {
                editor.canvas.discardActiveObject();
                editor.selectNextBox(false);
            }
            this.zoomToActiveBox();
            if (typeof editor !== 'undefined' && !editor.isIsolationMode) {
                editor.isIsolationMode = true;
                editor.updateIsolateView();

                const btnIsolate = document.getElementById('btnIsolate');
                if (btnIsolate) {
                    btnIsolate.classList.add('text-yellow-500');
                    btnIsolate.classList.remove('text-gray-400');
                }
            }
            this.updateSupervisedUI();
        }, 100);
    }

    zoomToActiveBox() {
        if (!editor || !editor.canvas) return;
        const target = editor.canvas.getActiveObject();
        if (!target) return;

        const padding = 100;
        const scaleX = editor.canvas.getWidth() / (target.width * target.scaleX + padding);
        const scaleY = editor.canvas.getHeight() / (target.height * target.scaleY + padding);
        let zoom = Math.min(scaleX, scaleY);
        zoom = Math.min(zoom, 5);
        zoom = Math.max(zoom, 1);

        editor.canvas.setZoom(zoom);

        const boxCenterX = target.left + (target.width * target.scaleX) / 2;
        const boxCenterY = target.top + (target.height * target.scaleY) / 2;
        const vpw = editor.canvas.getWidth();
        const vph = editor.canvas.getHeight();

        const vpt = editor.canvas.viewportTransform.slice();
        vpt[4] = vpw / 2 - boxCenterX * zoom;
        vpt[5] = vph / 2 - boxCenterY * zoom;
        editor.canvas.setViewportTransform(vpt);
    }

    finishSupervisedLabeling() {
        this.isSupervisedMode = false;
        this.updateSupervisedUI();
        if (typeof editor !== 'undefined' && editor.canvas) {
            if (editor.isIsolationMode) {
                editor.isIsolationMode = false;
                editor.updateIsolateView();
                const btnIsolate = document.getElementById('btnIsolate');
                if (btnIsolate) {
                    btnIsolate.classList.remove('text-yellow-500');
                    btnIsolate.classList.add('text-gray-400');
                }
            }
            editor.resetView();
            editor.canvas.discardActiveObject();
            editor.canvas.renderAll();
        }
        this.showToast(typeof window.t === 'function' ? window.t('supervised_done') || 'Supervised labeling completed.' : 'Supervised labeling completed.', 'success');
    }

    nextSupervisedBox() {
        if (!editor || !editor.canvas || !editor.showBoxes) return;
        const boxes = editor.canvas.getObjects('rect');
        const sorted = [...boxes].sort((a, b) => {
            const dy = a.top - b.top;
            if (Math.abs(dy) > 10) return dy;
            return a.left - b.left;
        });

        const current = editor.canvas.getActiveObject();
        if (current && current.type === 'rect') {
            const currentIdx = sorted.indexOf(current);
            if (currentIdx === sorted.length - 1) {
                this.finishSupervisedLabeling();
                return;
            }
        }

        editor.selectNextBox(false);
        this.zoomToActiveBox();
        if (typeof editor !== 'undefined' && !editor.isIsolationMode) {
            editor.isIsolationMode = true;
            editor.updateIsolateView();

            const btnIsolate = document.getElementById('btnIsolate');
            if (btnIsolate) {
                btnIsolate.classList.add('text-yellow-500');
                btnIsolate.classList.remove('text-gray-400');
            }
        }
        this.updateSupervisedUI();
    }

    prevSupervisedBox() {
        if (!editor || !editor.canvas) return;
        editor.selectNextBox(true);
        this.zoomToActiveBox();
        if (typeof editor !== 'undefined' && !editor.isIsolationMode) {
            editor.isIsolationMode = true;
            editor.updateIsolateView();

            const btnIsolate = document.getElementById('btnIsolate');
            if (btnIsolate) {
                btnIsolate.classList.add('text-yellow-500');
                btnIsolate.classList.remove('text-gray-400');
            }
        }
        this.updateSupervisedUI();
    }

    updateSupervisedUI() {
        const panel = document.getElementById('supervisedPanel');
        if (panel) {
            if (this.isSupervisedMode) {
                panel.classList.remove('hidden');
                panel.classList.add('flex');

                const textEl = document.getElementById('supervisedModeText');
                if (textEl && typeof editor !== 'undefined' && editor.canvas) {
                    const boxes = editor.canvas.getObjects('rect');
                    const sorted = [...boxes].sort((a, b) => {
                        const dy = a.top - b.top;
                        if (Math.abs(dy) > 10) return dy;
                        return a.left - b.left;
                    });
                    const current = editor.canvas.getActiveObject();
                    let currentIdx = 0;
                    if (current && current.type === 'rect') {
                        currentIdx = sorted.indexOf(current) + 1;
                    } else if (sorted.length > 0) {
                        currentIdx = 1;
                    }
                    textEl.innerText = `${currentIdx}/${sorted.length}`;
                }
            } else {
                panel.classList.add('hidden');
                panel.classList.remove('flex');
            }
        }
    }

    async autoLabelRegion(region) {
        if (!currentImage) return;

        const btn = document.getElementById('btnAutoLabelRegion');
        let icon = null;
        let originalClass = '';
        if (btn) {
            icon = btn.querySelector('i');
            if (icon) {
                originalClass = icon.className;
                icon.className = 'fa-solid fa-spinner fa-spin text-lg';
            }
            btn.disabled = true;
        }

        try {
            // Need to convert region to normalized coordinates relative to image
            const normRegion = {
                x: region.x / editor.imageWidth,
                y: region.y / editor.imageHeight,
                w: region.w / editor.imageWidth,
                h: region.h / editor.imageHeight
            };

            const data = await API.autoLabel(currentImage.id, normRegion);
            if (data.success) {
                if (data.boxes.length > 0) {
                    // Remove existing boxes whose center falls inside the drawn region
                    // to prevent duplicate bounding boxes
                    const existingBoxes = editor.canvas.getObjects('rect');
                    const toRemove = existingBoxes.filter(box => {
                        const boxCenterX = box.left + (box.width * box.scaleX) / 2;
                        const boxCenterY = box.top + (box.height * box.scaleY) / 2;
                        return boxCenterX >= region.x && boxCenterX <= region.x + region.w &&
                            boxCenterY >= region.y && boxCenterY <= region.y + region.h;
                    });
                    toRemove.forEach(box => editor.canvas.remove(box));

                    // Add the new boxes from AI
                    data.boxes.forEach(box => {
                        const rect = editor.addBoxToCanvas(box.class_id, box.x, box.y, box.w, box.h, true);
                        if (typeof window.collabSocket !== 'undefined' && window.collabSocket && window.collabSocket.connected) {
                            window.collabSocket.emit('box_created', {
                                image_id: currentImage.id,
                                box: {
                                    collabId: rect.collabId,
                                    class_id: rect.classId,
                                    x: box.x,
                                    y: box.y,
                                    w: box.w,
                                    h: box.h
                                }
                            });
                        }
                    });
                    editor.saveState();
                    if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
                }
            }
        } catch (e) {
            alert(e.message);
        } finally {
            if (icon) icon.className = originalClass;
            if (btn) btn.disabled = false;
        }
    }

    async autoLabelAll() {
        if (!this.allImages) return;

        const unlabeledImages = this.allImages.filter(img => !img.is_labeled || !img.classes || img.classes.length === 0);

        if (unlabeledImages.length === 0) {
            alert("No unlabeled images found.");
            return;
        }

        if (!confirm(`Found ${unlabeledImages.length} unlabeled images. Auto label all of them now? This may take some time.`)) {
            return;
        }

        const btn = document.getElementById('btnAutoLabelToggle');
        if (!btn) return;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;

        const progressContainer = document.getElementById('uploadProgressContainer');
        const progressBar = document.getElementById('uploadProgressBar');
        const progressText = document.getElementById('uploadProgressText');

        if (progressContainer) {
            progressContainer.classList.remove('hidden');
            if (progressBar) progressBar.style.width = '0%';
            if (progressText) progressText.innerText = `Auto Labeling... 0/${unlabeledImages.length}`;
        }

        let successCount = 0;
        let failCount = 0;
        let processedCount = 0;

        try {
            for (const img of unlabeledImages) {
                try {
                    const data = await API.autoLabel(img.id);
                    if (data.success || data.boxes) {
                        if (data.boxes && data.boxes.length > 0) {
                            const saveData = {
                                image_id: img.id,
                                labels: data.boxes,
                                flag_status: img.flag_status || false
                            };
                            const saveResult = await API.saveLabel(saveData);
                            if (saveResult.message || saveResult.success) {
                                successCount++;
                                img.classes = Array.from(new Set(data.boxes.map(b => b.class_id))).sort((a, b) => a - b);
                                img.is_labeled = true;

                                const el = document.getElementById(`img-${img.id}`);
                                if (el) {
                                    const checkIcon = el.querySelector('.fa-regular.fa-circle');
                                    if (checkIcon) {
                                        checkIcon.className = 'fa-solid fa-check text-secondary';
                                    }
                                }
                            } else {
                                failCount++;
                            }
                        } else {
                            // Inference successful but no objects found
                            successCount++;
                        }
                    } else {
                        // Failed inference
                        failCount++;
                    }
                } catch (err) {
                    console.error(`Failed to auto-label image ${img.id}:`, err);
                    failCount++;
                }

                processedCount++;
                if (progressContainer) {
                    const percentComplete = Math.round((processedCount / unlabeledImages.length) * 100);
                    if (progressBar) progressBar.style.width = percentComplete + '%';
                    if (progressText) progressText.innerText = `Auto Labeling... ${processedCount}/${unlabeledImages.length} (${percentComplete}%)`;
                }
            }

            alert(`Quá trình gán nhãn tự động hoàn tất.\nThành công: ${successCount} ảnh.\n${failCount > 0 ? `Thất bại: ${failCount} ảnh.` : ''}`);

            if (currentImage && unlabeledImages.find(img => img.id === currentImage.id)) {
                const updatedImg = this.allImages.find(img => img.id === currentImage.id);
                if (updatedImg.is_labeled) {
                    await this.selectImage(updatedImg);
                }
            }
        } catch (e) {
            alert("An error occurred during bulk auto-labeling: " + e.message);
        } finally {
            if (progressContainer) {
                progressContainer.classList.add('hidden');
            }
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }

    async changeSplitType(newType) {
        if (!currentImage) return;
        currentImage.split_type = newType;

        // Update styling of the dropdown itself
        const select = document.getElementById('splitTypeSelect');
        if (select) {
            let colorClasses = 'bg-gray-500/20 text-gray-400 border-gray-500/30';
            if (newType === 'train') colorClasses = 'bg-blue-500/20 text-blue-400 border-blue-500/30';
            else if (newType === 'val') colorClasses = 'bg-green-500/20 text-green-400 border-green-500/30';
            else if (newType === 'test') colorClasses = 'bg-purple-500/20 text-purple-400 border-purple-500/30';

            select.className = `absolute top-4 right-4 px-3 py-1 pr-6 text-xs font-bold rounded-md shadow z-10 backdrop-blur-sm uppercase tracking-wider border cursor-pointer outline-none hover:opacity-80 transition-opacity ${colorClasses}`;
        }

        if (this.allImages) {
            const localImg = this.allImages.find(img => img.id === currentImage.id);
            if (localImg) {
                localImg.split_type = newType;
            }
        }

        // Automatically save to the server
        await this.save(true);
    }

    openExportModal() {
        if (typeof window.updateSplitCounts === 'function') {
            window.updateSplitCounts();
        }
        document.getElementById('exportModal').classList.remove('hidden');
        this.onExportScopeChange();
    }

    async onExportScopeChange() {
        const scope = document.getElementById('exportScope').value;
        const tagsSelection = document.getElementById('exportTagsSelection');

        if (scope === 'tags') {
            tagsSelection.classList.remove('hidden');
            await this.populateExportTags();
        } else {
            tagsSelection.classList.add('hidden');
        }
        if (typeof window.updateSplitCounts === 'function') {
            window.updateSplitCounts();
        }
    }

    async populateExportTags() {
        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/tags`);
            if (res.ok) {
                const tags = await res.json();
                const container = document.getElementById('exportTagsList');
                container.innerHTML = '';

                if (tags.length === 0) {
                    container.innerHTML = '<div class="text-sm text-content-muted p-2">Không có tag nào trong project này.</div>';
                    return;
                }

                tags.forEach(tag => {
                    const label = document.createElement('label');
                    label.className = 'flex items-center space-x-2 text-sm text-content hover:bg-panel p-1 rounded cursor-pointer';
                    label.innerHTML = `
                        <input type="checkbox" name="exportTags" value="${tag.id}" class="form-checkbox h-4 w-4 text-primary rounded border-border bg-surface" onchange="if(typeof window.updateSplitCounts === 'function') window.updateSplitCounts()">
                        <span class="w-3 h-3 rounded-full" style="background-color: ${tag.color}"></span>
                        <span class="flex-grow">${tag.name}</span>
                        <span class="text-xs bg-surface-alt px-1.5 py-0.5 rounded text-content-muted">${tag.image_count || 0}</span>
                    `;
                    container.appendChild(label);
                });
            }
        } catch (e) {
            console.error('Failed to fetch tags', e);
        }
    }

    async executeExport() {
        const scope = document.getElementById('exportScope').value;
        const excludeFlagged = document.getElementById('exportExcludeFlagged').checked;
        const exportModeEl = document.querySelector('input[name="exportMode"]:checked');
        const exportMode = exportModeEl ? exportModeEl.value : 'all';

        const trainSplit = parseFloat(document.getElementById('exportTrainSplit').value) || 0;
        const valSplit = parseFloat(document.getElementById('exportValSplit').value) || 0;
        const testSplit = parseFloat(document.getElementById('exportTestSplit').value) || 0;

        if (trainSplit + valSplit + testSplit !== 100) {
            alert("Train, Val, and Test splits must sum exactly to 100%.");
            return;
        }

        const splits = {
            train: trainSplit / 100.0,
            val: valSplit / 100.0,
            test: testSplit / 100.0
        };

        const yoloVersion = document.getElementById('exportFormat').value;

        const criteria = {};

        if (scope === 'project') {
            criteria.project_ids = [PROJECT_ID];
        } else if (scope === 'tags') {
            const checkedTags = Array.from(document.querySelectorAll('input[name="exportTags"]:checked'))
                .map(cb => parseInt(cb.value));

            if (checkedTags.length === 0) {
                alert('Vui lòng chọn ít nhất 1 tag để export.');
                return;
            }
            criteria.project_ids = [PROJECT_ID];
            criteria.tags = checkedTags;
        } else if (scope === 'view') {
            const urlParams = new URLSearchParams(window.location.search);
            const urlViewId = urlParams.get('view_id');
            const viewVal = document.getElementById('viewFilter').value;
            if (!viewVal && !urlViewId) {
                alert('Please select a specific View in the sidebar filter to export by View.');
                return;
            }
            if (urlViewId) {
                criteria.view_id = urlViewId;
            } else if (viewVal === 'my_view') {
                criteria.view_id = 999;
            }
        } else if (scope === 'current') {
            if (!currentImage) {
                alert('No image selected.');
                return;
            }
            criteria.image_ids = [currentImage.id];
        }

        if (excludeFlagged) {
            criteria.exclude_flagged = true;
        }

        if (exportMode === 'tagged_only') {
            criteria.has_any_tag = true;
        }

        const btn = document.querySelector('#exportModal button:last-child');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exporting...';
        btn.disabled = true;

        try {
            const res = await fetch('/api/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...criteria,
                    splits: {
                        train: trainSplit,
                        val: valSplit,
                        test: testSplit
                    },
                    format: 'yolo'
                })
            });
            const result = await res.json();

            if (result.status === 'success') {
                closeModal('exportModal');

                // Reload images to get updated split_type from backend
                await loadImages(true);
                if (currentImage) {
                    const updated = currentWorkspace.allImages.find(i => i.id === currentImage.id);
                    if (updated) currentWorkspace.selectImage(updated);
                }

                const colabCode = `!pip install ultralytics
# 1. KẾT NỐI GOOGLE DRIVE VÀ LẤY DỮ LIỆU TỐC ĐỘ CAO
from google.colab import drive
import os
import yaml
import shutil
from google.colab import files

print("=== HỆ THỐNG KHỞI TẠO ===")
print("Đang yêu cầu quyền truy cập vào Google Drive của bạn...")
# Bảng thông báo của Google sẽ hiện ra, bạn cấp quyền cho nó nhé
drive.mount('/content/drive')

# Đường dẫn tới file trên Google Drive (Mặc định bạn để ở thư mục ngoài cùng)
drive_file_path = '/content/drive/MyDrive/exported_dataset.rar'
local_file_path = '/content/exported_dataset.rar'

# Bắt lỗi: Kiểm tra xem bạn đã up file lên Drive chưa
if not os.path.exists(drive_file_path):
    raise FileNotFoundError(f"Lỗi: Không tìm thấy file tại {drive_file_path}. Hãy mở Google Drive và tải file exported_dataset.rar lên trước nhé!")

print("Đang chép file từ Google Drive sang Colab... (Tốc độ thường > 100MB/s)")
# Chép file từ Drive vào bộ nhớ cực nhanh của Colab (nvme SSD)
shutil.copy(drive_file_path, local_file_path)

# Giải nén file
print(f"Đã copy thành công! Đang giải nén {local_file_path} vào thư mục dataset/...")
!unrar x -o+ "{local_file_path}" dataset/


# 2. CÀI ĐẶT THƯ VIỆN
!pip install ultralytics
from ultralytics import YOLO


# 3. TỰ ĐỘNG SỬA ĐƯỜNG DẪN TRONG DATA.YAML
yaml_path = 'dataset/exported_dataset/data.yaml'

if not os.path.exists(yaml_path):
    raise FileNotFoundError(f"Không tìm thấy file data.yaml tại {yaml_path}. Bạn hãy kiểm tra lại cấu trúc file nén!")

with open(yaml_path, 'r') as f:
    data_cfg = yaml.safe_load(f)

# Cập nhật đường dẫn chuẩn cho Colab
base_dir = os.path.abspath('dataset/exported_dataset')
data_cfg['path'] = base_dir
data_cfg['train'] = 'images/train'
data_cfg['val'] = 'images/test'

with open(yaml_path, 'w') as f:
    yaml.dump(data_cfg, f)

print(f"Đã cập nhật data.yaml với path: {base_dir}")


# 4. KHỞI TẠO MÔ HÌNH VÀ TRAINING
model = YOLO('${yoloVersion}')

results = model.train(
    data=yaml_path,
    epochs=200,
    patience=50,
    imgsz=1024,
    batch=-1,
    workers=8,
    cache=True,
    amp=True,
    close_mosaic=10,
    device=0,
    mosaic=1.0,
    mixup=0.15,
    copy_paste=0.2,
    auto_augment='randaugment'
)


# 5. XUẤT MÔ HÌNH SANG ĐỊNH DẠNG ONNX VÀ TẢI VỀ
print("Đang xuất mô hình sang định dạng ONNX...")
best_model_path = os.path.join(model.trainer.save_dir, 'weights/best.pt')
best_model = YOLO(best_model_path)
onnx_path = best_model.export(format='onnx', imgsz=1024, simplify=True)

print(f"Đã xuất file tại: {onnx_path}. Đang chuẩn bị tải về máy cá nhân...")
files.download(onnx_path)
`;

                document.getElementById('colabSnippetCode').textContent = colabCode;
                document.getElementById('colabCodeModal').classList.remove('hidden');
            } else {
                alert('Export Failed: ' + result.message);
            }
        } catch (e) {
            alert('Error: ' + e.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }

    setupAutocomplete() {
        const input = document.getElementById('newClassInput');
        const suggestionsBox = document.getElementById('newClassSuggestions');
        if (!input || !suggestionsBox) return;

        const updateSuggestions = () => {
            const val = input.value.trim().toLowerCase();
            if (!val) {
                suggestionsBox.classList.add('hidden');
                return;
            }

            const matches = projectClasses.filter(c => c.toLowerCase().includes(val));
            if (matches.length === 0) {
                suggestionsBox.classList.add('hidden');
                return;
            }

            suggestionsBox.innerHTML = '';
            matches.forEach(match => {
                const div = document.createElement('div');
                div.className = 'px-3 py-2 cursor-pointer hover:bg-primary hover:text-content-inv text-left truncate';
                div.textContent = match;
                div.onmousedown = (e) => { // Use mousedown so it triggers before input's blur event
                    e.preventDefault();
                    input.value = match;
                    suggestionsBox.classList.add('hidden');
                };
                suggestionsBox.appendChild(div);
            });
            suggestionsBox.classList.remove('hidden');
        };

        input.addEventListener('input', updateSuggestions);
        input.addEventListener('focus', updateSuggestions);

        input.addEventListener('blur', () => {
            suggestionsBox.classList.add('hidden');
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                suggestionsBox.classList.add('hidden');
                this.addNewClassFromSelection();
            }
        });
    }

    setupImageSearchAutocomplete() {
        const input = document.getElementById('imageSearchInput');
        const suggestionsBox = document.getElementById('imageSearchSuggestions');
        if (!input || !suggestionsBox) return;

        const updateSuggestions = () => {
            const val = input.value.trim().toLowerCase();
            if (!val) {
                suggestionsBox.classList.add('hidden');
                return;
            }

            if (!this.allImages || this.allImages.length === 0) {
                suggestionsBox.classList.add('hidden');
                return;
            }

            const matches = this.allImages.filter(img => img.filename.toLowerCase().includes(val));
            if (matches.length === 0) {
                suggestionsBox.classList.add('hidden');
                return;
            }

            const limit = 10;
            const displayedMatches = matches.slice(0, limit);

            suggestionsBox.innerHTML = '';
            displayedMatches.forEach(img => {
                const div = document.createElement('div');
                div.className = 'px-3 py-2 cursor-pointer hover:bg-primary hover:text-content-inv text-left truncate border-b border-border last:border-b-0 flex items-center justify-between';

                const labelIcon = img.is_labeled
                    ? '<i class="fa-solid fa-check text-green-500 text-[10px]"></i>'
                    : '<i class="fa-regular fa-circle text-content-muted text-[10px]"></i>';

                div.innerHTML = `<span class="truncate pr-2">${img.filename}</span>${labelIcon}`;
                div.onmousedown = (e) => {
                    e.preventDefault();
                    input.value = img.filename;
                    suggestionsBox.classList.add('hidden');
                    this.selectImage(img);
                };
                suggestionsBox.appendChild(div);
            });
            suggestionsBox.classList.remove('hidden');
        };

        input.addEventListener('input', updateSuggestions);
        input.addEventListener('focus', updateSuggestions);

        input.addEventListener('blur', () => {
            suggestionsBox.classList.add('hidden');
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                suggestionsBox.classList.add('hidden');
                this.searchAndSelectImage();
            }
        });
    }

    searchAndSelectImage() {
        const input = document.getElementById('imageSearchInput');
        if (!input) return;
        const val = input.value.trim().toLowerCase();
        if (!val) {
            alert('Vui lòng nhập tên file ảnh cần tìm!');
            return;
        }

        if (!this.allImages || this.allImages.length === 0) {
            alert('Không có ảnh nào trong project!');
            return;
        }

        let matchedImg = this.allImages.find(img => img.filename.toLowerCase() === val);
        if (!matchedImg) {
            matchedImg = this.allImages.find(img => img.filename.toLowerCase().includes(val));
        }

        if (matchedImg) {
            this.selectImage(matchedImg);
            const imgEl = document.getElementById(`img-${matchedImg.id}`);
            if (imgEl) {
                imgEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        } else {
            alert(`Không tìm thấy ảnh có tên gần giống "${input.value}"!`);
        }
    }

    /**
     * Apply a class (by index) to all selected bounding box objects.
     * Supports both single and multi-selection via getActiveObjects().
     */
    _applyClassToObjects(classIdx) {
        if (typeof editor === 'undefined' || !editor.canvas) return;

        const selectedObjects = editor.canvas.getActiveObjects();
        if (!selectedObjects || selectedObjects.length === 0) return;

        const color = editor.colors[classIdx % 20];
        const className = projectClasses[classIdx];

        selectedObjects.forEach(obj => {
            if (obj.type !== 'rect') return; // Only update bounding boxes
            obj.classId = classIdx;
            obj.set('stroke', color);
            if (obj.__labelTag) {
                obj.__labelTag.set('fill', color);
            }
            if (obj.__labelText) {
                obj.__labelText.set('text', className);
            }
        });

        editor.canvas.renderAll();
        // Show info for the first selected object
        if (selectedObjects.length === 1) {
            editor.updateSelectionInfo(selectedObjects[0]);
        }
        if (typeof updateClassListVisibility === 'function') updateClassListVisibility();
        this.save(true);
    }

    async addNewClassFromSelection() {
        const input = document.getElementById('newClassInput');
        if (!input) return;

        const newClassName = input.value.trim();
        if (!newClassName) {
            alert('Please enter a class name.');
            return;
        }

        // Validate if at least one bounding box is selected
        if (typeof editor === 'undefined' || !editor.canvas || !editor.canvas.getActiveObject()) {
            alert('Vui lòng chọn hoặc vẽ một bounding box trước khi thêm class mới!');
            return;
        }

        // Check if class already exists (case insensitive)
        const existingClassIdx = projectClasses.findIndex(c => c.toLowerCase() === newClassName.toLowerCase());
        if (existingClassIdx !== -1) {
            // Assign all selected boxes to the existing class
            this._applyClassToObjects(existingClassIdx);
            input.value = '';
            return;
        }

        const btn = input.nextElementSibling;
        if (btn) {
            btn.textContent = '...';
            btn.disabled = true;
        }

        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/classes`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newClassName })
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.error || 'Failed to add class');
            }

            const data = await res.json();
            projectClasses = data.classes;

            // Re-render class list in the UI
            this.renderClasses();
            this.renderClassFilters();

            const newClassIdx = projectClasses.length - 1;

            // Assign all selected boxes to the newly added class
            this._applyClassToObjects(newClassIdx);

            input.value = '';

        } catch (e) {
            console.error("Error adding class:", e);
            alert('Error adding class: ' + e.message);
        } finally {
            if (btn) {
                btn.textContent = 'Add';
                btn.disabled = false;
            }
        }
    }

    async deleteClass(idx, className) {
        if (!confirm(`Are you sure you want to delete the class "${className}"? This will remove all bounding boxes using this class from all images and cannot be undone.`)) {
            return;
        }

        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/classes/${idx}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.error || 'Failed to delete class');
            }

            const data = await res.json();
            projectClasses = data.classes;

            // Re-render class list and filters in UI
            this.renderClasses();
            this.renderClassFilters();

            // Refresh the images list to reflect any removed labels
            await loadImages(true);

            // Reload the active image if one is selected, so it reflects updated boxes
            if (currentImage) {
                const updatedImage = currentWorkspace.allImages.find(img => img.id === currentImage.id);
                if (updatedImage) {
                    this.selectImage(updatedImage);
                } else {
                    editor.clear();
                }
            }

        } catch (e) {
            console.error("Error deleting class:", e);
            alert('Error deleting class: ' + e.message);
        }
    }

    async uploadImages(event) {
        const files = event.target.files;
        if (!files || files.length === 0) return;

        // Lấy danh sách tên file đang có trong dự án
        const existingFilenames = new Set((this.allImages || []).map(img => img.filename));
        const isFolderUpload = event.target.id === 'folderUploadInput';

        let addedFiles = [];
        let skippedCount = 0;

        const duplicateSuffixRegex = /\(\d+\)\.[a-zA-Z0-9]+$/;

        for (let i = 0; i < files.length; i++) {
            const file = files[i];

            // Bỏ qua các file có đuôi (1), (2)... (được coi là file trùng)
            if (duplicateSuffixRegex.test(file.name)) {
                skippedCount++;
                continue;
            }

            // Nếu là upload folder và file đã tồn tại (trùng tên), thì bỏ qua
            if (isFolderUpload && existingFilenames.has(file.name)) {
                skippedCount++;
                continue;
            }
            addedFiles.push(file);
        }

        if (addedFiles.length === 0) {
            this.showToast(`Đã bỏ qua ${skippedCount} file vì đã tồn tại trong dự án. Không có file mới nào để tải lên.`, 'info');
            event.target.value = ''; // reset input
            return;
        }

        // Find the main upload button icon to show spinner
        const btn = document.querySelector('button[title="Upload Images"]');
        const originalHtml = btn ? btn.innerHTML : '';
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            btn.disabled = true;
        }

        const progressContainer = document.getElementById('uploadProgressContainer');
        const progressBar = document.getElementById('uploadProgressBar');
        const progressText = document.getElementById('uploadProgressText');

        if (progressContainer) {
            progressContainer.classList.remove('hidden');
            if (progressBar) progressBar.style.width = '0%';
            if (progressText) progressText.innerText = 'Uploading... 0%';
        }

        try {
            const CHUNK_SIZE = 50;
            let totalUploadedChunks = 0;
            const totalChunks = Math.ceil(addedFiles.length / CHUNK_SIZE);
            let totalBytes = addedFiles.reduce((acc, f) => acc + f.size, 0);
            let uploadedBytesBeforeCurrentChunk = 0;

            for (let i = 0; i < addedFiles.length; i += CHUNK_SIZE) {
                const chunk = addedFiles.slice(i, i + CHUNK_SIZE);
                const formData = new FormData();
                let currentChunkBytes = 0;
                for (let file of chunk) {
                    formData.append('files', file);
                    currentChunkBytes += file.size;
                }
                formData.append('skip_sync', 'true');

                await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', `/api/projects/${PROJECT_ID}/upload`, true);

                    xhr.upload.onprogress = (event) => {
                        if (event.lengthComputable && totalBytes > 0) {
                            const currentTotalLoaded = uploadedBytesBeforeCurrentChunk + event.loaded;
                            const percentComplete = Math.min(100, Math.round((currentTotalLoaded / totalBytes) * 100));
                            if (progressBar) progressBar.style.width = percentComplete + '%';
                            if (progressText) progressText.innerText = `Uploading chunk ${totalUploadedChunks + 1}/${totalChunks}... ${percentComplete}%`;
                        }
                    };

                    xhr.onload = async () => {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            uploadedBytesBeforeCurrentChunk += currentChunkBytes;
                            totalUploadedChunks++;
                            resolve(JSON.parse(xhr.responseText));
                        } else {
                            reject(new Error('Upload failed with status ' + xhr.status));
                        }
                    };

                    xhr.onerror = () => reject(new Error('Upload failed due to network error'));
                    xhr.send(formData);
                });
            }

            if (progressText) progressText.innerText = 'Syncing database...';
            try {
                const syncResponse = await fetch(`/api/projects/scan/${PROJECT_ID}`, { method: 'POST' });
                if (!syncResponse.ok) {
                    console.error('Failed to sync database after upload', await syncResponse.text());
                }
            } catch (err) {
                console.error('Error triggering sync:', err);
            }

            await loadImages(true);
            await this.loadProjectInfo(); // Reload classes in case dataset files like classes.txt or data.yaml were uploaded

            if (skippedCount > 0) {
                this.showToast(`Đã tải lên ${addedFiles.length} file. Đã bỏ qua ${skippedCount} file (do trùng tên hoặc đuôi (1), (2)).`, 'info');
            } else {
                this.showToast(`Đã tải lên ${addedFiles.length} file thành công.`, 'success');
            }
        } catch (e) {
            this.showToast('Lỗi tải ảnh: ' + e.message, 'error');
        } finally {
            if (btn) {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }
            if (progressContainer) {
                progressContainer.classList.add('hidden');
            }
            event.target.value = ''; // reset input
        }
    }

    async showClassExamplesModal() {
        const modal = document.getElementById('classExamplesModal');
        const content = document.getElementById('classExamplesContent');
        if (!modal || !content) return;

        modal.classList.remove('hidden');
        content.innerHTML = '<div class="text-center text-content-muted py-10"><i class="fa-solid fa-spinner fa-spin text-3xl mb-3"></i><div data-i18n="loading">Loading...</div></div>';

        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/class-examples`);
            if (!res.ok) throw new Error('Failed to load examples');
            const data = await res.json();

            const classes = data.classes;
            this.classExamplesData = data.examples;
            this.classExamplesIndex = {};

            if (classes.length === 0) {
                content.innerHTML = '<div class="text-center text-content-muted py-10" data-i18n="no_classes">No classes found</div>';
                return;
            }

            let html = '<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">';

            // We will render canvases and load images after HTML is set
            const renderTasks = [];

            for (let i = 0; i < classes.length; i++) {
                const className = classes[i];
                const examplesList = this.classExamplesData[i.toString()];
                this.classExamplesIndex[i] = 0;

                // Determine color - editor might not be initialized yet but it usually is
                const color = (typeof editor !== 'undefined' && editor.colors) ? editor.colors[i % 20] : '#3b82f6';

                html += `
                    <div class="bg-panel border border-border rounded flex flex-col overflow-hidden">
                        <div class="bg-sidebar px-3 py-2 border-b border-border font-semibold text-sm truncate flex items-center" title="${className}">
                            <span class="inline-block w-3 h-3 rounded-full mr-2" style="background-color: ${color}"></span>
                            ${className}
                        </div>
                        <div class="flex-1 aspect-square relative bg-surface flex items-center justify-center p-2 group">
                `;

                if (examplesList && examplesList.length > 0) {
                    html += `<canvas id="example-canvas-${i}" class="max-w-full max-h-full object-contain shadow-sm border border-border rounded"></canvas>`;

                    if (examplesList.length > 1) {
                        html += `
                            <div class="absolute inset-0 flex items-center justify-between px-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                <button class="bg-black/50 text-white rounded-full w-8 h-8 flex items-center justify-center hover:bg-black/80" onclick="currentWorkspace.changeClassExample(${i}, -1, '${color}')">
                                    <i class="fa-solid fa-chevron-left"></i>
                                </button>
                                <button class="bg-black/50 text-white rounded-full w-8 h-8 flex items-center justify-center hover:bg-black/80" onclick="currentWorkspace.changeClassExample(${i}, 1, '${color}')">
                                    <i class="fa-solid fa-chevron-right"></i>
                                </button>
                            </div>
                            <div class="absolute bottom-2 right-2 bg-black/50 text-white text-xs px-2 py-1 rounded" id="example-counter-${i}">1/${examplesList.length}</div>
                        `;
                    }

                    renderTasks.push({ index: i, color: color });
                } else {
                    html += `<div class="text-content-muted text-xs text-center"><i class="fa-regular fa-image text-2xl mb-2 opacity-50"></i><br>No examples yet</div>`;
                }

                html += `
                        </div>
                    </div>
                `;
            }

            html += '</div>';
            content.innerHTML = html;

            // Load images and draw on canvas
            renderTasks.forEach(task => {
                this.renderClassExample(task.index, task.color);
            });

        } catch (e) {
            console.error(e);
            content.innerHTML = `<div class="text-center text-red-500 py-10">Error loading examples: ${e.message}</div>`;
        }
    }

    changeClassExample(classIndex, direction, color) {
        const examplesList = this.classExamplesData[classIndex.toString()];
        if (!examplesList || examplesList.length <= 1) return;

        let currentIndex = this.classExamplesIndex[classIndex];
        currentIndex += direction;

        if (currentIndex < 0) currentIndex = examplesList.length - 1;
        if (currentIndex >= examplesList.length) currentIndex = 0;

        this.classExamplesIndex[classIndex] = currentIndex;

        const counter = document.getElementById(`example-counter-${classIndex}`);
        if (counter) {
            counter.innerText = `${currentIndex + 1}/${examplesList.length}`;
        }

        this.renderClassExample(classIndex, color);
    }

    renderClassExample(classIndex, color) {
        const examplesList = this.classExamplesData[classIndex.toString()];
        if (!examplesList) return;

        const currentIndex = this.classExamplesIndex[classIndex];
        const example = examplesList[currentIndex];

        const img = new Image();
        img.onload = () => {
            const canvas = document.getElementById(`example-canvas-${classIndex}`);
            if (!canvas) return;

            const ctx = canvas.getContext('2d');
            const [cx, cy, cw, ch] = example.bbox;

            // YOLO relative to absolute
            const absW = cw * img.width;
            const absH = ch * img.height;
            const absX = (cx * img.width) - (absW / 2);
            const absY = (cy * img.height) - (absH / 2);

            // Add some padding to show context
            const pad = Math.max(absW, absH) * 0.3;
            let sx = Math.max(0, absX - pad);
            let sy = Math.max(0, absY - pad);
            let sw = Math.min(img.width - sx, absW + pad * 2);
            let sh = Math.min(img.height - sy, absH + pad * 2);

            canvas.width = sw;
            canvas.height = sh;

            // Draw cropped region
            ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);

            // Draw bounding box
            ctx.strokeStyle = color;
            ctx.lineWidth = Math.max(2, sw / 150);
            ctx.strokeRect(absX - sx, absY - sy, absW, absH);

            // Add subtle fill
            ctx.fillStyle = color + '33'; // 20% opacity
            ctx.fillRect(absX - sx, absY - sy, absW, absH);
        };
        img.src = `/api/image_data/${example.image_id}`;
    }
}

function calculateIoU(box1, box2) {
    const b1_x = box1.x_center !== undefined ? box1.x_center : box1.x;
    const b1_y = box1.y_center !== undefined ? box1.y_center : box1.y;
    const b1_w = box1.width !== undefined ? box1.width : box1.w;
    const b1_h = box1.height !== undefined ? box1.height : box1.h;

    const b2_x = box2.x_center !== undefined ? box2.x_center : box2.x;
    const b2_y = box2.y_center !== undefined ? box2.y_center : box2.y;
    const b2_w = box2.width !== undefined ? box2.width : box2.w;
    const b2_h = box2.height !== undefined ? box2.height : box2.h;

    const x1_min = b1_x - b1_w / 2;
    const y1_min = b1_y - b1_h / 2;
    const x1_max = b1_x + b1_w / 2;
    const y1_max = b1_y + b1_h / 2;

    const x2_min = b2_x - b2_w / 2;
    const y2_min = b2_y - b2_h / 2;
    const x2_max = b2_x + b2_w / 2;
    const y2_max = b2_y + b2_h / 2;

    const inter_x_min = Math.max(x1_min, x2_min);
    const inter_y_min = Math.max(y1_min, y2_min);
    const inter_x_max = Math.min(x1_max, x2_max);
    const inter_y_max = Math.min(y1_max, y2_max);

    if (inter_x_min < inter_x_max && inter_y_min < inter_y_max) {
        const inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min);
        const area1 = b1_w * b1_h;
        const area2 = b2_w * b2_h;
        const union_area = area1 + area2 - inter_area;
        return inter_area / union_area;
    }
    return 0;
}

function applyOverlapFilter() {
    loadImages(false);
}

function toggleSidebarFilters() {
    const content = document.getElementById('sidebarFiltersContent');
    const icon = document.getElementById('toggleFiltersIcon');
    if (content && icon) {
        if (content.classList.contains('hidden')) {
            content.classList.remove('hidden');
            icon.classList.remove('fa-chevron-down');
            icon.classList.add('fa-chevron-up');
        } else {
            content.classList.add('hidden');
            icon.classList.remove('fa-chevron-up');
            icon.classList.add('fa-chevron-down');
        }
    }
}

function copyImageName(event, filename) {
    event.preventDefault();
    const el = event.currentTarget;
    const nameWithoutExt = filename.replace(/\.[^/.]+$/, "");
    navigator.clipboard.writeText(nameWithoutExt).then(() => {
        if (el) {
            const originalBg = el.style.backgroundColor;
            const originalColor = el.style.color;
            el.style.backgroundColor = '#10b981';
            el.style.color = '#fff';
            setTimeout(() => {
                el.style.backgroundColor = originalBg;
                el.style.color = originalColor;
            }, 300);
        }
    }).catch(err => {
        console.error('Failed to copy', err);
    });
}

const currentWorkspace = new Workspace();

let advancedClassFilterActive = false;
let advancedSelectedClasses = [];

function openAdvancedClassFilterModal() {
    const modal = document.getElementById('advancedClassFilterModal');
    const list = document.getElementById('advancedClassFilterList');
    list.innerHTML = '';

    if (typeof projectClasses !== 'undefined' && projectClasses && projectClasses.length > 0) {
        projectClasses.forEach((cls, idx) => {
            const isChecked = advancedSelectedClasses.includes(idx) ? 'checked' : '';
            const color = editor.colors[idx % 20];
            const div = document.createElement('div');
            div.className = 'flex flex-col items-center justify-center p-2 hover:bg-panel rounded border border-transparent hover:border-border cursor-pointer text-center min-w-0';

            div.innerHTML = `
                <div class="flex items-center gap-1.5 mb-1.5">
                    <input type="radio" name="adv_class_radio" value="${idx}" id="adv-class-${idx}" class="adv-class-radio text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer" ${isChecked}>
                    <span class="inline-block w-2.5 h-2.5 rounded-full" style="background-color: ${color}"></span>
                </div>
                <label for="adv-class-${idx}" class="w-full cursor-pointer select-none text-[11px] font-medium text-content truncate block" title="${cls}">
                    ${cls}
                </label>
            `;
            // Click on the div to select the radio
            div.onclick = (e) => {
                if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'LABEL') {
                    const radio = div.querySelector('input');
                    radio.checked = true;
                }
            };
            list.appendChild(div);
        });
    } else {
        list.innerHTML = '<span class="italic text-content-muted">No classes available.</span>';
    }

    modal.classList.remove('hidden');
}

function closeAdvancedClassFilterModal() {
    document.getElementById('advancedClassFilterModal').classList.add('hidden');
}

function clearAdvancedClassFilter() {
    advancedClassFilterActive = false;
    advancedSelectedClasses = [];

    // Clear selections in the modal
    const radios = document.querySelectorAll('.adv-class-radio');
    radios.forEach(r => r.checked = false);

    document.getElementById('advancedClassFilterModal').classList.add('hidden');
    loadImages(false);
}

function applyAdvancedClassFilter() {
    const selectedRadio = document.querySelector('.adv-class-radio:checked');
    if (selectedRadio) {
        advancedSelectedClasses = [parseInt(selectedRadio.value)];
        advancedClassFilterActive = true;

        // Uncheck normal class filter checkboxes to prevent conflict
        const normalCheckboxes = document.querySelectorAll('.class-filter-checkbox');
        normalCheckboxes.forEach(cb => cb.checked = false);
    } else {
        advancedClassFilterActive = false;
        advancedSelectedClasses = [];
    }

    document.getElementById('advancedClassFilterModal').classList.add('hidden');
    loadImages(false);
}

async function loadImages(fetchFromServer = true) {
    if (fetchFromServer || !currentWorkspace.allImages) {
        const viewFilterEl = document.getElementById('viewFilter');

        // Parse view_id from URL
        const urlParams = new URLSearchParams(window.location.search);
        const urlViewId = urlParams.get('view_id');

        if (urlViewId) {
            viewFilterEl.value = 'my_view';
            viewFilterEl.disabled = true;
        }

        const view = viewFilterEl.value;
        const flag = document.getElementById('flagFilter').value;

        const filters = { project_id: PROJECT_ID };

        if (urlViewId) {
            filters.view_id = urlViewId;
        } else if (view === 'my_view') {
            filters.view_id = 999; // existing mock fallback
        }

        if (flag) {
            if (flag === 'Labeled') {
                filters.is_labeled = 'true';
            } else if (flag === 'Unlabeled') {
                filters.is_labeled = 'false';
            } else if (flag === 'Reviewed') {
                filters.is_reviewed = 'true';
            } else if (flag === 'NotReviewed') {
                filters.is_reviewed = 'false';
            } else {
                filters.flag_status = flag;
            }
        }

        const images = await API.getImages(filters);
        currentWorkspace.allImages = images;
    }

    const totalImageCountEl = document.getElementById('totalImageCount');
    if (totalImageCountEl) {
        totalImageCountEl.innerText = `(${currentWorkspace.allImages ? currentWorkspace.allImages.length : 0})`;
    }

    // Read active class filters
    const checkboxes = document.querySelectorAll('.class-filter-checkbox');
    const selectedClasses = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => parseInt(cb.value));

    // Filter images
    let filteredImages = currentWorkspace.allImages;
    if (advancedClassFilterActive && advancedSelectedClasses.length > 0) {
        // Advanced Filter: Image must contain ONLY the selected class(es)
        filteredImages = filteredImages.filter(img => {
            const imgClasses = img.classes || [];
            // Get unique classes in this image
            const uniqueImgClasses = [...new Set(imgClasses)];

            // Check exact match: length must be same, and all selected classes must be present
            if (uniqueImgClasses.length !== advancedSelectedClasses.length) {
                return false;
            }
            return advancedSelectedClasses.every(c => uniqueImgClasses.includes(c));
        });
    } else if (selectedClasses.length > 0) {
        // Normal Filter: Image must contain all selected classes (but can contain others)
        filteredImages = filteredImages.filter(img => {
            const imgClasses = img.classes || [];
            return selectedClasses.every(c => imgClasses.includes(c));
        });
    }

    // Overlap filter
    const overlapInput = document.getElementById('overlapThresholdInput');
    const overlapThreshold = overlapInput ? parseFloat(overlapInput.value) : NaN;

    // Add overlap info to images if threshold is set
    filteredImages.forEach(img => {
        img.overlapThreshold = isNaN(overlapThreshold) ? null : overlapThreshold;
        img.overlapCount = 0;
        img.overlappingBoxes = new Set();
        if (!isNaN(overlapThreshold) && img.boxes && img.boxes.length > 1) {
            for (let i = 0; i < img.boxes.length; i++) {
                for (let j = i + 1; j < img.boxes.length; j++) {
                    const iou = calculateIoU(img.boxes[i], img.boxes[j]);
                    if (iou >= overlapThreshold) {
                        img.overlappingBoxes.add(i);
                        img.overlappingBoxes.add(j);
                    }
                }
            }
            img.overlapCount = img.overlappingBoxes.size;
        }
    });

    if (!isNaN(overlapThreshold)) {
        filteredImages = filteredImages.filter(img => img.overlapCount > 0);
    }

    const container = document.getElementById('imageList');
    if (filteredImages.length === 0) {
        container.innerHTML = '<div class="p-4 text-xs text-content-muted italic text-center">Không có ảnh nào khớp với bộ lọc</div>';
    } else {
        container.innerHTML = filteredImages.map(img => {
            const isActive = typeof currentImage !== 'undefined' && currentImage && currentImage.id === img.id;
            const activeClasses = isActive ? 'bg-blue-600/30 border-l-4 border-blue-500 text-white font-semibold' : 'bg-surface text-content-muted border-l-0 border-transparent';

            // Overlap UI classes
            const overlapClasses = (!isNaN(overlapThreshold) && img.overlapCount > 0)
                ? 'border-l-[3px] border-b-[3px] border-l-red-500 border-b-red-500'
                : '';

            return `
            <div class="px-4 py-3 cursor-pointer border-b border-border flex justify-between items-center text-sm hover:bg-panel transition-all image-item ${activeClasses} ${overlapClasses}" 
                 id="img-${img.id}" 
                 onclick="currentWorkspace.selectImage(currentWorkspace.allImages.find(i => i.id === ${img.id}))"
                 oncontextmenu="copyImageName(event, '${img.filename}')">
                <input type="checkbox" class="image-checkbox rounded border-border bg-panel text-primary focus:ring-primary w-4 h-4 flex-shrink-0 mr-2" 
                       data-id="${img.id}" 
                       onclick="event.stopPropagation(); currentWorkspace.handleCheckboxClick(event, ${img.id})" 
                       ${currentWorkspace.selectedImageIds.has(img.id) ? 'checked' : ''}>
                <span class="truncate pr-2 flex-1" title="${img.filename}">${img.filename}</span>
                <div class="flex items-center gap-2">
                    <div class="flex items-center gap-1 active-users-indicator" id="active-users-${img.id}"></div>
                    ${img.overlapCount > 0 ? `<span class="text-xs font-bold text-red-500 bg-red-500/20 px-1.5 py-0.5 rounded" title="${img.overlapCount} overlapping boxes">${img.overlapCount}</span>` : ''}
                    ${img.is_reviewed ? '<i class="fa-solid fa-circle-check text-green-500"></i>' : ''}
                    ${img.flag_status === 'Flagged' ? '<i class="fa-solid fa-flag text-red-500"></i>' : ''}
                    ${img.is_labeled ? '<i class="fa-solid fa-check text-secondary"></i>' : '<i class="fa-regular fa-circle text-content-muted"></i>'}
                </div>
            </div>
            `;
        }).join('');
    }

    currentWorkspace.imageList = filteredImages;

    const listedCountEl = document.getElementById('listedCount');
    if (listedCountEl) {
        listedCountEl.innerText = filteredImages.length;
    }

    if (typeof editor !== 'undefined' && typeof currentImage !== 'undefined' && currentImage) {
        editor.triggerGlowForClasses(selectedClasses);
    }

    if (typeof window.updateAllUserIndicators === 'function') {
        window.updateAllUserIndicators();
    }
}

function selectClass(id, el) {
    editor.setActiveClass(id);
    editor.setFocusClass(id);

    document.querySelectorAll('.class-item').forEach(e => {
        e.classList.remove('bg-panel', 'border-l-2', 'border-primary', 'text-primary');
        e.classList.add('bg-surface', 'text-content-muted', 'border-border');
    });

    let target = el;
    if (!target) {
        target = document.querySelector(`.class-item[data-class-id="${id}"]`);
    }

    if (target && editor.focusClassId === id) {
        target.classList.remove('bg-surface', 'text-content-muted', 'border-border');
        target.classList.add('bg-panel', 'border-l-2', 'border-primary', 'text-primary');
    }

    // Auto-switch to Draw Mode ONLY if no object is selected
    if (typeof editor !== 'undefined') {
        const active = editor.canvas.getActiveObject();
        if (!active) {
            editor.setMode('draw');
        }
    }
}

async function openAssignModal() {
    try {
        const projectIdInput = document.querySelector('input[name="project_id"]');
        if (!projectIdInput) return;
        const projectId = projectIdInput.value;
        const stats = await API.getAssignStats(projectId);

        if (stats.all.unassigned === 0) {
            alert('Lỗi: Tổng ảnh chưa phân công hiện tại là 0.');
            return;
        }

        document.getElementById('assignModal').classList.remove('hidden');

        const select = document.querySelector('select[name="assign_mode"]');
        if (select) {
            const optionBoth = select.querySelector('option[value="both"]');
            const optionLabeled = select.querySelector('option[value="labeled"]');
            const optionUnlabeled = select.querySelector('option[value="unlabeled"]');

            if (optionBoth) optionBoth.dataset.suffix = ` (${stats.all.assigned}/${stats.all.unassigned})`;
            if (optionLabeled) optionLabeled.dataset.suffix = ` (${stats.labeled.assigned}/${stats.labeled.unassigned})`;
            if (optionUnlabeled) optionUnlabeled.dataset.suffix = ` (${stats.unlabeled.assigned}/${stats.unlabeled.unassigned})`;

            // Reapply translations to update the visible text with suffixes
            if (typeof applyTranslations === 'function') {
                applyTranslations();
            }
        }
    } catch (err) {
        console.error("Failed to load assign stats", err);
    }
}

function closeModal(id) {
    document.getElementById(id).classList.add('hidden');
}

function toggleSearchHeader(forceState) {
    const header = document.getElementById('searchHeader');
    const chevron = document.getElementById('searchHeaderChevron');
    if (!header || !chevron) return;

    let toOpen;
    if (typeof forceState !== 'undefined') {
        toOpen = forceState;
    } else {
        toOpen = header.classList.contains('-translate-y-full');
    }

    if (toOpen) {
        header.classList.remove('-translate-y-full');
        header.classList.add('translate-y-0');
        chevron.classList.remove('fa-chevron-bottom');
        chevron.classList.add('fa-chevron-top');
        localStorage.setItem('searchHeaderOpen', 'true');
    } else {
        header.classList.remove('translate-y-0');
        header.classList.add('-translate-y-full');
        chevron.classList.remove('fa-chevron-top');
        chevron.classList.add('fa-chevron-bottom');
        localStorage.setItem('searchHeaderOpen', 'false');
    }
}

document.getElementById('assignForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());

    // Kiểm tra logic trước khi submit
    const projectId = data.project_id;
    const stats = await API.getAssignStats(projectId);

    let unassigned = 0;
    if (data.assign_mode === 'labeled') {
        unassigned = stats.labeled.unassigned;
    } else if (data.assign_mode === 'unlabeled') {
        unassigned = stats.unlabeled.unassigned;
    } else {
        unassigned = stats.all.unassigned;
    }

    if (unassigned === 0) {
        alert('Lỗi: Tổng ảnh chưa phân công hiện tại là 0.');
        return;
    }

    let requestedCount = parseInt(data.count, 10);
    if (isNaN(requestedCount) || requestedCount <= 0) {
        alert('Lỗi: Số lượng không hợp lệ.');
        return;
    }

    // Nếu số lượng yêu cầu lớn hơn số lượng chưa phân công thì gán bằng số lượng chưa phân công
    if (requestedCount > unassigned) {
        requestedCount = unassigned;
    }

    // 1. Create View
    const viewRes = await API.createView({ name: data.view_name, project_id: data.project_id });

    // 2. Assign
    const assignData = {
        view_id: viewRes.id,
        count: requestedCount,
        project_id: data.project_id,
        assign_mode: data.assign_mode
    };

    try {
        const res = await API.assignView(assignData);
        if (res.error) {
            alert(res.error);
        } else {
            alert(res.message || `Phân công thành công ${res.assigned_count || data.count} ảnh.`);
            document.getElementById('assignModal').classList.add('hidden');
            loadImages();
        }
    } catch (err) {
        console.error(err);
        alert('Có lỗi xảy ra khi phân công.');
    }
});

// Search Filter
document.getElementById('classSearch').addEventListener('input', (e) => {
    updateClassListVisibility();
});

function updateClassListVisibility() {
    if (typeof editor === 'undefined' || !editor.canvas) return;
    const boxes = editor.getBoxesYOLO();
    const presentClassIds = new Set(boxes.map(b => parseInt(b.class_id)).filter(id => !isNaN(id)));

    // Calculate count for each class
    const classCounts = {};
    boxes.forEach(b => {
        const cid = b.class_id;
        classCounts[cid] = (classCounts[cid] || 0) + 1;
    });

    const searchInput = document.getElementById('classSearch');
    const term = searchInput ? searchInput.value.toLowerCase() : '';

    const showSeq = editor.showSequenceNumbers;

    document.querySelectorAll('.class-item').forEach(el => {
        const classId = parseInt(el.getAttribute('data-class-id'));
        const classNameSpan = el.querySelector('span');
        const classNameText = classNameSpan ? classNameSpan.innerText.toLowerCase() : el.innerText.toLowerCase();
        const matchesSearch = classNameText.includes(term);
        const isPresent = presentClassIds.has(classId);

        if (matchesSearch && isPresent) {
            el.style.display = 'flex';
        } else {
            el.style.display = 'none';
        }

        // Update badge count and visibility
        const badge = el.querySelector('.class-count-badge');
        if (badge) {
            const count = classCounts[classId] || 0;
            badge.innerText = count;
            if (showSeq && count > 0) {
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
    });
}
function toggleDropdown(event, buttonId, dropdownId, dropdownWidth) {
    if (event) event.stopPropagation();
    const btn = document.getElementById(buttonId);
    const dropdown = document.getElementById(dropdownId);
    if (!btn || !dropdown) return;

    // Hide other dropdowns first
    const allDropdowns = ['autoLabelDropdown', 'sequenceDropdown'];
    allDropdowns.forEach(id => {
        if (id !== dropdownId) {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        }
    });

    const isHidden = dropdown.classList.contains('hidden');
    if (isHidden) {
        dropdown.classList.remove('hidden');
        positionFixedDropdown(btn, dropdown, dropdownWidth);
    } else {
        dropdown.classList.add('hidden');
    }
}

function positionFixedDropdown(btn, dropdown, dropdownWidth) {
    if (!btn || !dropdown || dropdown.classList.contains('hidden')) return;
    const rect = btn.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    dropdown.style.top = (rect.bottom + 4) + 'px';
    let leftPos = rect.left;
    if (leftPos + dropdownWidth > window.innerWidth) {
        leftPos = window.innerWidth - dropdownWidth - 8;
    }
    dropdown.style.left = leftPos + 'px';
}

document.addEventListener('click', function (event) {
    // Hide autoLabelDropdown
    const dropdown = document.getElementById('autoLabelDropdown');
    if (dropdown && !dropdown.classList.contains('hidden') && !event.target.closest('#autoLabelDropdownWrapper')) {
        dropdown.classList.add('hidden');
    }
    // Hide sequenceDropdown
    const seqDropdown = document.getElementById('sequenceDropdown');
    if (seqDropdown && !seqDropdown.classList.contains('hidden') && !event.target.closest('#btnShowSequenceNumbers') && !event.target.closest('#sequenceDropdown')) {
        seqDropdown.classList.add('hidden');
    }
});

window.addEventListener('resize', () => {
    positionFixedDropdown(document.getElementById('btnAutoLabelToggle'), document.getElementById('autoLabelDropdown'), 192);
    positionFixedDropdown(document.getElementById('btnShowSequenceNumbers'), document.getElementById('sequenceDropdown'), 192);
});

window.addEventListener('scroll', () => {
    positionFixedDropdown(document.getElementById('btnAutoLabelToggle'), document.getElementById('autoLabelDropdown'), 192);
    positionFixedDropdown(document.getElementById('btnShowSequenceNumbers'), document.getElementById('sequenceDropdown'), 192);
}, true);

function initSplitSlider() {
    const container = document.getElementById('splitSliderContainer');
    const handle1 = document.getElementById('splitHandle1');
    const handle2 = document.getElementById('splitHandle2');
    const barTrain = document.getElementById('splitBarTrain');
    const barVal = document.getElementById('splitBarVal');
    const barTest = document.getElementById('splitBarTest');

    const inputTrain = document.getElementById('exportTrainSplit');
    const inputVal = document.getElementById('exportValSplit');
    const inputTest = document.getElementById('exportTestSplit');

    const lblTrainPct = document.getElementById('lblTrainPct');
    const lblValPct = document.getElementById('lblValPct');
    const lblTestPct = document.getElementById('lblTestPct');

    const lblTrainCount = document.getElementById('lblTrainCount');
    const lblValCount = document.getElementById('lblValCount');
    const lblTestCount = document.getElementById('lblTestCount');

    if (!container) return;

    let isDragging1 = false;
    let isDragging2 = false;

    let p1 = 80;
    let p2 = 90;

    function updateUI() {
        if (p1 < 0) p1 = 0;
        if (p2 > 100) p2 = 100;
        if (p1 > p2) {
            if (isDragging1) p1 = p2;
            else p2 = p1;
        }

        const trainPct = Math.round(p1);
        const valPct = Math.round(p2 - p1);
        const testPct = Math.round(100 - p2);

        barTrain.style.width = p1 + '%';
        barVal.style.left = p1 + '%';
        barVal.style.width = (p2 - p1) + '%';
        barTest.style.left = p2 + '%';
        barTest.style.width = (100 - p2) + '%';

        handle1.style.left = p1 + '%';
        handle2.style.left = p2 + '%';

        inputTrain.value = trainPct;
        inputVal.value = valPct;
        inputTest.value = testPct;

        lblTrainPct.textContent = trainPct;
        lblValPct.textContent = valPct;
        lblTestPct.textContent = testPct;

        window.updateSplitCounts = function () {
            let total = 0;
            if (currentWorkspace && currentWorkspace.allImages) {
                const scopeEl = document.getElementById('exportScope');
                const excludeFlagged = document.getElementById('exportExcludeFlagged')?.checked;

                let filteredImages = currentWorkspace.allImages.filter(img => img.is_labeled === true);

                if (excludeFlagged) {
                    filteredImages = filteredImages.filter(img => img.flag_status !== 'Flagged');
                }

                if (scopeEl && scopeEl.value === 'tags') {
                    const checkedTags = Array.from(document.querySelectorAll('input[name="exportTags"]:checked')).map(el => parseInt(el.value));
                    if (checkedTags.length > 0) {
                        filteredImages = filteredImages.filter(img => {
                            if (!img.tags || !Array.isArray(img.tags)) return false;
                            return img.tags.some(t => checkedTags.includes(t.id));
                        });
                        total = filteredImages.length;
                    } else {
                        total = 0;
                    }
                } else if (scopeEl && scopeEl.value === 'current') {
                    // For current image only
                    total = 1;
                } else {
                    total = filteredImages.length;
                }
            }

            const trainCount = Math.round(total * trainPct / 100);
            const valCount = Math.round(total * valPct / 100);
            const testCount = total - trainCount - valCount;

            if (lblTrainCount) lblTrainCount.textContent = trainCount;
            if (lblValCount) lblValCount.textContent = valCount;
            if (lblTestCount) lblTestCount.textContent = testCount;
        };

        window.updateSplitCounts();
    }

    function onMouseMove(e) {
        if (!isDragging1 && !isDragging2) return;

        const rect = container.getBoundingClientRect();
        let x = e.clientX - rect.left;
        let pct = (x / rect.width) * 100;

        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;

        if (isDragging1) {
            p1 = pct;
            if (p1 > p2) p1 = p2;
        } else if (isDragging2) {
            p2 = pct;
            if (p2 < p1) p2 = p1;
        }
        updateUI();
    }

    function onMouseUp() {
        isDragging1 = false;
        isDragging2 = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }

    handle1.addEventListener('mousedown', (e) => {
        isDragging1 = true;
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
        e.preventDefault();
    });

    handle2.addEventListener('mousedown', (e) => {
        isDragging2 = true;
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
        e.preventDefault();
    });

    updateUI();
}

document.addEventListener('DOMContentLoaded', () => {
    initSplitSlider();

    // Initialize Search Header state from localStorage
    const searchHeaderOpen = localStorage.getItem('searchHeaderOpen');
    if (searchHeaderOpen === 'false') {
        toggleSearchHeader(false);
    }

    const dropdownContainer = document.getElementById('uploadDropdownContainer');
    const dropdownMenu = document.getElementById('uploadDropdownMenu');
    let hideTimeout;

    if (dropdownContainer && dropdownMenu) {
        dropdownContainer.addEventListener('mouseenter', () => {
            clearTimeout(hideTimeout);
            dropdownMenu.classList.remove('hidden');
            dropdownMenu.classList.add('flex');
        });

        dropdownContainer.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                dropdownMenu.classList.add('hidden');
                dropdownMenu.classList.remove('flex');
            }, 1500); // 1.5s delay
        });
    }
});
