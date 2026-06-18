// Initialized in workspace.html: const PROJECT_ID = ...

const editor = new Editor('c');
let currentImage = null;
let projectClasses = [];

class Workspace {
    constructor() {
        this.init();
        this.imageList = [];
    }

    async init() {
        // 1. Get Project Details (for classes)

        await this.loadProjectInfo();
        this.setupAutocomplete();
        await loadImages();

        // Hotkeys
        document.addEventListener('keydown', (e) => {
            // Ignore hotkeys if typing in an input text field
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                return;
            }

            if (e.key === 'Delete' || e.key === 'Backspace' || e.key.toLowerCase() === 'q') {
                editor.deleteSelected();
            }
            if (e.key.toLowerCase() === 's' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.save();
            }
            if (e.key.toLowerCase() === 'd' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                editor.duplicateSelected();
            } else if (e.key.toLowerCase() === 'd') {
                // Single D for Draw Mode
                editor.setMode('draw');
            }
            if (e.key.toLowerCase() === 'v') editor.setMode('select');
            if (e.key.toLowerCase() === 'f') this.toggleFlag();
            if (e.key.toLowerCase() === 'l') this.toggleLockBox();
            if (e.key.toLowerCase() === 'h') this.toggleImageVisibility();
            if (e.key.toLowerCase() === 'i') this.toggleIsolateMode();

            if (e.key.toLowerCase() === 'i') this.toggleIsolateMode();
            if (e.key.toLowerCase() === 'a') editor.toggleStickyMove();

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
        currentImage = image;
        document.getElementById('currentFileName').textContent = image.filename;

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
            el.classList.remove('bg-panel', 'border-l-2', 'border-primary', 'text-primary');
            el.classList.add('bg-surface', 'text-content-muted');
        });
        const el = document.getElementById(`img-${image.id}`);
        if (el) {
            el.classList.remove('bg-surface', 'text-content-muted');
            el.classList.add('bg-panel', 'border-l-2', 'border-primary', 'text-primary');
        }

        // Update Flag Button
        this.updateFlagButton();

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

        // 1. Get Labels first?
        const labels = await API.getLabel(image.id);

        // 2. Load Image
        // We need to fetch image dimensions first or let Fabric handle it.
        // Fabric handles it.

        fabric.Image.fromURL(url, (img) => {
            if (!img) { alert('Failed to load image'); return; }
            editor.loadImage(img);
            editor.loadBoxes(labels);

            // Trigger visual glow effect for active class filters
            const checkboxes = document.querySelectorAll('.class-filter-checkbox');
            const selectedClasses = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => parseInt(cb.value));

            editor.triggerGlowForClasses(selectedClasses);

            // Update Inspection View with Image Metadata
            this.updateImageStats(img, labels.length);
        });
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

                this.renderImageList(this.allImages);

                if (this.allImages.length > 0) {
                    const nextIndex = Math.min(currentIndex, this.allImages.length - 1);
                    this.loadImage(this.allImages[nextIndex].id);
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
            btn.classList.remove('text-gray-400');
        } else {
            btn.classList.remove('text-red-500');
            btn.classList.add('text-gray-400');
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

    async save(silent = false) {
        if (!currentImage) return;

        const btn = document.querySelector('button[onclick="currentWorkspace.save()"]');
        let originalText = 'Saved';
        let originalClasses = 'bg-primary hover:bg-blue-500 text-content-inv text-sm font-medium px-4 py-1.5 rounded ml-2';
        if (btn) {
            originalText = btn.textContent;
            originalClasses = btn.className;
        }

        try {
            const boxes = editor.getBoxesYOLO();

            const data = {
                image_id: currentImage.id,
                labels: boxes,
                flag_status: currentImage.flag_status,
                split_type: currentImage.split_type
            };

            await API.saveLabel(data);

            // Update local classes cache for filtering and checkmark status
            if (currentWorkspace.allImages) {
                const localImg = currentWorkspace.allImages.find(i => i.id === currentImage.id);
                if (localImg) {
                    const uniqueClasses = Array.from(new Set(boxes.map(b => b.class_id))).sort((a, b) => a - b);
                    localImg.classes = uniqueClasses;
                    localImg.is_labeled = true;

                    // Update check icon in DOM without reloading the whole list
                    const el = document.getElementById(`img-${currentImage.id}`);
                    if (el) {
                        const checkIcon = el.querySelector('.fa-regular.fa-circle');
                        if (checkIcon) {
                            checkIcon.className = 'fa-solid fa-check text-secondary';
                        }
                    }
                }
            }

            if (!silent && btn) {
                btn.textContent = 'Success!';
                btn.className = 'bg-green-500 hover:bg-green-600 text-white text-sm font-medium px-4 py-1.5 rounded ml-2';
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.className = originalClasses;
                }, 1000);
            }
        } catch (error) {
            console.error('Save error:', error);
            if (!silent && btn) {
                btn.textContent = 'Failed!';
                btn.className = 'bg-red-500 hover:bg-red-600 text-white text-sm font-medium px-4 py-1.5 rounded ml-2';
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.className = originalClasses;
                }, 1000);
            }
            if (!silent) {
                alert('Save failed: ' + (error.message || 'Unknown error'));
            }
        }
    }

    async autoLabel() {
        if (!currentImage) return;

        const btn = document.getElementById('btnAutoLabelToggle');
        if (!btn) return;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        btn.disabled = true;

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

        let successCount = 0;
        let failCount = 0;

        try {
            for (const img of unlabeledImages) {
                try {
                    const data = await API.autoLabel(img.id);
                    if (data.success && data.boxes && data.boxes.length > 0) {
                        const saveData = {
                            image_id: img.id,
                            labels: data.boxes,
                            flag_status: img.flag_status || false
                        };
                        const saveResult = await API.saveLabel(saveData);
                        if (saveResult.success) {
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
                        // Empty boxes or failed inference, optionally count as fail
                    }
                } catch (err) {
                    console.error(`Failed to auto-label image ${img.id}:`, err);
                    failCount++;
                }
            }

            alert(`Auto-labeled and saved ${successCount} images. ${failCount > 0 ? `Failed on ${failCount} images.` : ''}`);

            if (currentImage && unlabeledImages.find(img => img.id === currentImage.id)) {
                const updatedImg = this.allImages.find(img => img.id === currentImage.id);
                if (updatedImg.is_labeled) {
                    this.loadImage(currentImage.id);
                }
            }
        } catch (e) {
            alert("An error occurred during bulk auto-labeling: " + e.message);
        } finally {
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
    }

    async executeExport() {
        const scope = document.getElementById('exportScope').value;
        const excludeFlagged = document.getElementById('exportExcludeFlagged').checked;

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
        } else if (scope === 'view') {
            const viewVal = document.getElementById('viewFilter').value;
            if (!viewVal) {
                alert('Please select a specific View in the sidebar filter to export by View.');
                return;
            }
            // Mock View ID for now as per loadImages logic
            criteria.view_id = 999;
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

                // Construct Colab Snippet
                const colabCode = `# HƯỚNG DẪN ĐÀO TẠO TRÊN GOOGLE COLAB:
# 1. Nén thư mục '${result.export_path}' thành file dataset.zip
# 2. Upload file exported_dataset.zip lên Google Colab
# 3. Dán và chạy đoạn code sau:

!unzip -q exported_dataset.zip -d dataset
!pip install ultralytics
from ultralytics import YOLO

# Khởi tạo mô hình
model = YOLO('${yoloVersion}')

# Bắt đầu training
results = model.train(data='dataset/data.yaml', epochs=100, imgsz=640)`;

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

    async addNewClassFromSelection() {
        const input = document.getElementById('newClassInput');
        if (!input) return;

        const newClassName = input.value.trim();
        if (!newClassName) {
            alert('Please enter a class name.');
            return;
        }

        // Validate if a bounding box is selected
        if (typeof editor === 'undefined' || !editor.canvas || !editor.canvas.getActiveObject()) {
            alert('Vui lòng chọn hoặc vẽ một bounding box trước khi thêm class mới!');
            return;
        }

        // Check if class already exists (case insensitive)
        const existingClassIdx = projectClasses.findIndex(c => c.toLowerCase() === newClassName.toLowerCase());
        if (existingClassIdx !== -1) {
            // Assign to existing class
            const active = editor.canvas.getActiveObject();
            if (active) {
                active.classId = existingClassIdx;
                active.set('stroke', editor.colors[existingClassIdx % 20]);
                if (active.__labelTag) {
                    active.__labelTag.set('fill', editor.colors[existingClassIdx % 20]);
                }
                if (active.__labelText) {
                    active.__labelText.set('text', projectClasses[existingClassIdx]);
                }
                editor.canvas.renderAll();
                editor.updateSelectionInfo(active);
                this.save(true);
            }
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

            // If an object is selected, update its class to the newly added class
            if (typeof editor !== 'undefined' && editor.canvas) {
                const active = editor.canvas.getActiveObject();
                if (active) {
                    active.classId = newClassIdx;
                    active.set('stroke', editor.colors[newClassIdx % 20]);

                    // Update label tag background if it exists
                    if (active.__labelTag) {
                        active.__labelTag.set('fill', editor.colors[newClassIdx % 20]);
                    }
                    if (active.__labelText) {
                        active.__labelText.set('text', projectClasses[newClassIdx]);
                    }

                    editor.canvas.renderAll();
                    editor.updateSelectionInfo();
                    this.save(true); // auto save
                }
            }

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

        // Find the main upload button icon to show spinner
        const btn = document.querySelector('button[title="Upload Images"]');
        const originalHtml = btn ? btn.innerHTML : '';
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            btn.disabled = true;
        }

        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }

        try {
            const res = await fetch(`/api/projects/${PROJECT_ID}/upload`, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) throw new Error('Upload failed');
            const data = await res.json();

            // alert(`Tải lên thành công ${data.count} file.`);
            await loadImages(true);
            await this.loadProjectInfo(); // Reload classes in case dataset files like classes.txt or data.yaml were uploaded
        } catch (e) {
            alert('Lỗi tải ảnh: ' + e.message);
        } finally {
            if (btn) {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }
            event.target.value = ''; // reset input
        }
    }
}

const currentWorkspace = new Workspace();

async function loadImages(fetchFromServer = true) {
    if (fetchFromServer || !currentWorkspace.allImages) {
        const view = document.getElementById('viewFilter').value;
        const flag = document.getElementById('flagFilter').value;

        const filters = { project_id: PROJECT_ID };
        if (view) filters.view_id = 999;
        if (flag) {
            if (flag === 'Labeled') {
                filters.is_labeled = 'true';
            } else if (flag === 'Unlabeled') {
                filters.is_labeled = 'false';
            } else {
                filters.flag_status = flag;
            }
        }

        const images = await API.getImages(filters);
        currentWorkspace.allImages = images;
    }

    // Read active class filters
    const checkboxes = document.querySelectorAll('.class-filter-checkbox');
    const selectedClasses = Array.from(checkboxes)
        .filter(cb => cb.checked)
        .map(cb => parseInt(cb.value));

    // Filter images
    let filteredImages = currentWorkspace.allImages;
    if (selectedClasses.length > 0) {
        filteredImages = currentWorkspace.allImages.filter(img => {
            const imgClasses = img.classes || [];
            return selectedClasses.every(c => imgClasses.includes(c));
        });
    }

    const container = document.getElementById('imageList');
    if (filteredImages.length === 0) {
        container.innerHTML = '<div class="p-4 text-xs text-content-muted italic text-center">Không có ảnh nào khớp với bộ lọc nhãn</div>';
    } else {
        container.innerHTML = filteredImages.map(img => `
            <div class="px-4 py-3 cursor-pointer border-b border-border flex justify-between items-center text-sm hover:bg-panel transition-colors bg-surface text-content-muted image-item" 
                 id="img-${img.id}" 
                 onclick="currentWorkspace.selectImage({id: ${img.id}, filename: '${img.filename}', flag_status: '${img.flag_status}', split_type: '${img.split_type}'})">
                <span class="truncate pr-2 flex-1" title="${img.filename}">${img.filename}</span>
                <div class="flex items-center gap-2">
                    ${img.flag_status === 'Flagged' ? '<i class="fa-solid fa-flag text-red-500"></i>' : ''}
                    ${img.is_labeled ? '<i class="fa-solid fa-check text-secondary"></i>' : '<i class="fa-regular fa-circle text-content-muted"></i>'}
                </div>
            </div>
        `).join('');
    }

    currentWorkspace.imageList = filteredImages;

    // Trigger canvas glow for the filtered classes if an image is loaded
    if (typeof editor !== 'undefined' && typeof currentImage !== 'undefined' && currentImage) {
        editor.triggerGlowForClasses(selectedClasses);
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

function openAssignModal() {
    document.getElementById('assignModal').classList.remove('hidden');
}

function closeModal(id) {
    document.getElementById(id).classList.add('hidden');
}

document.getElementById('assignForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());

    // 1. Create View
    const viewRes = await API.createView({ name: data.view_name, project_id: data.project_id });

    // 2. Assign
    const assignData = {
        view_id: viewRes.id,
        count: data.count,
        project_id: data.project_id
    };

    const res = await API.assignView(assignData);
    alert(res.message);
    document.getElementById('assignModal').classList.add('hidden');
    loadImages();
});

// Search Filter
document.getElementById('classSearch').addEventListener('input', (e) => {
    updateClassListVisibility();
});

function updateClassListVisibility() {
    if (typeof editor === 'undefined' || !editor.canvas) return;
    const boxes = editor.getBoxesYOLO();
    const presentClassIds = new Set(boxes.map(b => b.class_id));

    const searchInput = document.getElementById('classSearch');
    const term = searchInput ? searchInput.value.toLowerCase() : '';

    document.querySelectorAll('.class-item').forEach(el => {
        const classId = parseInt(el.getAttribute('data-class-id'));
        const text = el.innerText.toLowerCase();
        const matchesSearch = text.includes(term);
        const isPresent = presentClassIds.has(classId);

        if (isPresent && matchesSearch) {
            el.style.display = 'flex';
        } else {
            el.style.display = 'none';
        }
    });

    // If focusClassId is set but it's no longer present on canvas, unfocus it
    if (editor.focusClassId !== null && !presentClassIds.has(editor.focusClassId)) {
        editor.setFocusClass(editor.focusClassId); // Toggle off

        // Remove highlight from the class item
        const target = document.querySelector(`.class-item[data-class-id="${editor.focusClassId}"]`);
        if (target) {
            target.classList.remove('bg-panel', 'border-l-2', 'border-primary', 'text-primary');
            target.classList.add('bg-surface', 'text-content-muted', 'border-border');
        }
    }
}
document.addEventListener('click', function (event) { const dropdown = document.getElementById('autoLabelDropdown'); if (dropdown && !dropdown.classList.contains('hidden') && !event.target.closest('#autoLabelDropdownWrapper')) { dropdown.classList.add('hidden'); } });

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

        window.updateSplitCounts = function() {
            let total = 0;
            if (currentWorkspace && currentWorkspace.allImages) {
                total = currentWorkspace.allImages.length;
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

document.addEventListener('DOMContentLoaded', initSplitSlider);
