function selectAllListedImages() {
    const listedImages = Array.isArray(currentWorkspace.imageList) ? currentWorkspace.imageList : [];
    if (listedImages.length === 0) return;

    listedImages.forEach(image => currentWorkspace.selectedImageIds.add(image.id));
    currentWorkspace.lastCheckedId = listedImages[listedImages.length - 1].id;
    document.querySelectorAll('.image-checkbox').forEach(cb => {
        cb.checked = currentWorkspace.selectedImageIds.has(parseInt(cb.dataset.id, 10));
    });
    currentWorkspace.updateSelectionUI();
}

async function openBulkTagSelector(action = 'assign') {
    const imageIds = Array.from(currentWorkspace.selectedImageIds);
    if (imageIds.length === 0) {
        alert('Vui lòng chọn ít nhất một ảnh.');
        return;
    }

    await currentWorkspace.loadProjectTags(true);
    const modal = document.getElementById('bulkTagSelectorModal');
    const container = document.getElementById('bulkTagSelectorList');
    const title = document.getElementById('bulkTagSelectorTitle');
    const summary = document.getElementById('bulkTagSelectorSummary');
    if (!modal || !container) return;

    const normalizedAction = action === 'unassign' ? 'unassign' : 'assign';
    modal.dataset.action = normalizedAction;
    if (title) {
        title.textContent = normalizedAction === 'unassign'
            ? `Gỡ tag khỏi ${imageIds.length} ảnh`
            : `Gắn tag cho ${imageIds.length} ảnh`;
    }
    if (summary) {
        summary.textContent = normalizedAction === 'unassign'
            ? 'Các tag đã chọn sẽ được gỡ khỏi toàn bộ ảnh đang chọn.'
            : 'Các tag đã chọn sẽ được thêm vào toàn bộ ảnh đang chọn.';
    }

    if (!currentWorkspace.projectTags || currentWorkspace.projectTags.length === 0) {
        container.innerHTML = '<div class="text-sm text-content-muted p-2">Project chưa có tag. Hãy tạo tag trong Tag Manager trước.</div>';
    } else {
        container.innerHTML = currentWorkspace.projectTags.map(tag => `
            <label class="flex items-center space-x-2 text-sm text-content hover:bg-surface p-2 rounded cursor-pointer border border-transparent hover:border-border transition-colors">
                <input type="checkbox" name="bulkImageTag" value="${tag.id}" class="form-checkbox h-4 w-4 text-primary rounded border-border bg-surface focus:ring-primary focus:ring-offset-panel">
                <span class="w-3 h-3 rounded-full flex-shrink-0" style="background-color: ${tag.color}"></span>
                <span class="flex-grow">${tag.name}</span>
                <span class="text-xs text-content-muted">${tag.image_count || 0}</span>
            </label>
        `).join('');
    }

    modal.classList.remove('hidden');
}

async function saveBulkImageTags() {
    const imageIds = Array.from(currentWorkspace.selectedImageIds);
    const checkedBoxes = Array.from(document.querySelectorAll('input[name="bulkImageTag"]:checked'));
    const tagIds = checkedBoxes.map(cb => parseInt(cb.value, 10));
    if (imageIds.length === 0) {
        alert('Không còn ảnh nào được chọn.');
        return;
    }
    if (tagIds.length === 0) {
        alert('Vui lòng chọn ít nhất một tag.');
        return;
    }

    const modal = document.getElementById('bulkTagSelectorModal');
    const action = modal?.dataset.action === 'unassign' ? 'unassign' : 'assign';
    const saveButton = document.getElementById('bulkTagSaveBtn');
    if (saveButton) saveButton.disabled = true;

    try {
        const res = await fetch(`/api/projects/${PROJECT_ID}/bulk_assign_tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_ids: imageIds, tag_ids: tagIds, action })
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || 'Không thể cập nhật tag.');
        }

        const affectedImageIds = new Set(imageIds);
        const selectedTags = (currentWorkspace.projectTags || []).filter(
            tag => tagIds.includes(parseInt(tag.id, 10))
        );
        const applyTagAction = image => {
            if (!image || !affectedImageIds.has(image.id)) return;
            if (action === 'unassign') {
                image.tags = (image.tags || []).filter(
                    tag => !tagIds.includes(parseInt(tag.id, 10))
                );
                return;
            }

            const tagsById = new Map(
                (image.tags || []).map(tag => [parseInt(tag.id, 10), tag])
            );
            selectedTags.forEach(tag => tagsById.set(parseInt(tag.id, 10), tag));
            image.tags = Array.from(tagsById.values());
        };

        (currentWorkspace.allImages || []).forEach(applyTagAction);
        if (currentImage && !(currentWorkspace.allImages || []).includes(currentImage)) {
            applyTagAction(currentImage);
        }
        currentWorkspace.renderImageTags();
        currentWorkspace.clearImageSelection();
        closeModal('bulkTagSelectorModal');

        await currentWorkspace.loadProjectTags(true);
        await loadImages(true);

        const message = action === 'unassign'
            ? `Đã gỡ tag khỏi ${imageIds.length} ảnh.`
            : `Đã gắn tag cho ${imageIds.length} ảnh.`;
        if (typeof window.showToast === 'function') {
            window.showToast(message, 'success');
        }
    } catch (error) {
        console.error('Bulk tag update error:', error);
        alert(error.message || 'Không thể cập nhật tag.');
    } finally {
        if (saveButton) saveButton.disabled = false;
    }
}
