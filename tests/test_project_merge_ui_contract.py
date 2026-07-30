from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_merge_ui_uses_per_source_selection_contract():
    dashboard = (REPO_ROOT / 'templates' / 'dashboard.html').read_text(encoding='utf-8')

    assert 'function collectMergeSources()' in dashboard
    assert 'mergeSourceMode-${p.id}' in dashboard
    assert 'mergeSourceTags-${projectId}' in dashboard
    assert dashboard.count('sources: sources') == 2
    assert 'projectIds.length < 2' not in dashboard
    assert 'sources.length < 1' in dashboard


def test_merge_ui_translations_describe_create_and_tag_modes():
    translations = (REPO_ROOT / 'static' / 'js' / 'i18n.js').read_text(encoding='utf-8')

    assert 'Create / Merge Project' in translations
    assert 'Tạo / Gộp Dự án' in translations
    assert 'Only images matching tags' in translations
    assert 'Chỉ lấy ảnh theo tag' in translations
    assert 'Select Source Projects (Min 1)' in translations
