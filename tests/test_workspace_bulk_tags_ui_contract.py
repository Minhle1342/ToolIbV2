from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_workspace_exposes_select_all_and_bulk_tag_actions():
    template = (REPO_ROOT / 'templates' / 'workspace.html').read_text(encoding='utf-8')

    assert 'selectAllListedImages()' in template
    assert "openBulkTagSelector('assign')" in template
    assert "openBulkTagSelector('unassign')" in template
    assert 'id="bulkTagSelectorModal"' in template
    assert 'saveBulkImageTags()' in template
    assert "filename='js/workspace_bulk_tags.js'" in template


def test_workspace_bulk_tag_flow_uses_selected_images_and_existing_api():
    workspace = (REPO_ROOT / 'static' / 'js' / 'workspace_bulk_tags.js').read_text(encoding='utf-8')

    assert 'function selectAllListedImages()' in workspace
    assert 'listedImages.forEach(image => currentWorkspace.selectedImageIds.add(image.id))' in workspace
    assert "async function openBulkTagSelector(action = 'assign')" in workspace
    assert 'async function saveBulkImageTags()' in workspace
    assert '/bulk_assign_tags' in workspace
    assert 'JSON.stringify({ image_ids: imageIds, tag_ids: tagIds, action })' in workspace
    assert 'await currentWorkspace.loadProjectTags(true);' in workspace
