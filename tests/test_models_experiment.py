import io
from pathlib import Path

import cv2
import numpy as np
import pytest

import routes
from inference import YOLOInference
from models import AIModel, db
from test_helpers import assert_safe_test_database, create_isolated_test_app


@pytest.fixture
def isolated_app(tmp_path):
    db_path = tmp_path / 'models_experiment.db'
    app = create_isolated_test_app(str(db_path))
    with app.app_context():
        assert_safe_test_database(app, expected_root=str(tmp_path))
        db.drop_all()
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()
            db.engine.dispose()


@pytest.fixture
def client(isolated_app):
    return isolated_app.test_client()


def jpeg_bytes(width=200, height=100):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok
    return encoded.tobytes()


def test_preprocess_supports_letterbox_and_stretch_geometry():
    engine = YOLOInference.__new__(YOLOInference)
    image = np.zeros((100, 200, 3), dtype=np.uint8)

    letterbox_blob, original_size, letterbox_scales, letterbox_padding = (
        engine.preprocess(
            img=image,
            target_size=(320, 320),
            resize_mode='letterbox',
        )
    )
    stretch_blob, _, stretch_scales, stretch_padding = engine.preprocess(
        img=image,
        target_size=(320, 320),
        resize_mode='stretch',
    )

    assert letterbox_blob.shape == (1, 3, 320, 320)
    assert stretch_blob.shape == (1, 3, 320, 320)
    assert original_size == (200, 100)
    assert letterbox_scales == pytest.approx((1.6, 1.6))
    assert letterbox_padding == (0, 80)
    assert stretch_scales == pytest.approx((1.6, 3.2))
    assert stretch_padding == (0, 0)


def test_stretch_postprocess_restores_original_coordinates():
    engine = YOLOInference.__new__(YOLOInference)
    engine.input_width = 640
    engine.input_height = 640
    rows = np.array([[80, 80, 240, 240, 0.9, 0]], dtype=np.float32)

    result = engine._postprocess_end2end_output(
        rows,
        conf_threshold=0.25,
        full_w=200,
        full_h=100,
        orig_w=200,
        orig_h=100,
        scale_x=1.6,
        scale_y=3.2,
        pad_w=0,
        pad_h=0,
        offset_x=0,
        offset_y=0,
        input_width=320,
        input_height=320,
    )

    assert result['success'] is True
    assert len(result['boxes']) == 1
    box = result['boxes'][0]
    assert box['x'] == pytest.approx(0.5)
    assert box['y'] == pytest.approx(0.5)
    assert box['w'] == pytest.approx(0.5)
    assert box['h'] == pytest.approx(0.5)


def test_models_test_rejects_more_than_three_models(client):
    response = client.post(
        '/api/models/test',
        data={
            'image': (io.BytesIO(jpeg_bytes()), 'sample.jpg'),
            'model_ids': '1,2,3,4',
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == (
        'Select at most 3 models for one comparison'
    )


def test_models_test_accepts_three_distinct_models(
    isolated_app,
    client,
    monkeypatch,
):
    with isolated_app.app_context():
        models = [
            AIModel(
                name=f'YOLO comparison {index}',
                filename=f'comparison_{index}.onnx',
                model_type='detection',
            )
            for index in range(1, 4)
        ]
        db.session.add_all(models)
        db.session.commit()
        model_ids = [model.id for model in models]

    calls = []

    class FakeEngine:
        class_names = {}

        def __init__(self, model_path):
            self.model_path = model_path

        def predict(self, image_path, **kwargs):
            calls.append((self.model_path, kwargs))
            return {'success': True, 'boxes': []}

    real_exists = routes.os.path.exists
    monkeypatch.setattr(routes, 'YOLOInference', FakeEngine)
    monkeypatch.setattr(
        routes.os.path,
        'exists',
        lambda path: (
            True if str(path).endswith('.onnx') else real_exists(path)
        ),
    )

    response = client.post(
        '/api/models/test',
        data={
            'image': (io.BytesIO(jpeg_bytes()), 'sample.jpg'),
            'model_ids': ','.join(str(model_id) for model_id in model_ids),
            'image_size': '640',
            'resize_mode': 'letterbox',
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    assert set(response.get_json()) == {str(model_id) for model_id in model_ids}
    assert len(calls) == 3


def test_models_test_passes_experiment_inference_settings(
    isolated_app,
    client,
    monkeypatch,
):
    with isolated_app.app_context():
        model = AIModel(
            name='Dynamic YOLO',
            filename='dynamic_test.onnx',
            model_type='detection',
        )
        db.session.add(model)
        db.session.commit()
        model_id = model.id

    captured = {}

    class FakeEngine:
        class_names = {0: 'object'}

        def __init__(self, model_path):
            captured['model_path'] = model_path

        def predict(self, image_path, **kwargs):
            captured['image_path'] = image_path
            captured['kwargs'] = kwargs
            return {'success': True, 'boxes': []}

    real_exists = routes.os.path.exists
    monkeypatch.setattr(routes, 'YOLOInference', FakeEngine)
    monkeypatch.setattr(
        routes.os.path,
        'exists',
        lambda path: True if str(path).endswith('dynamic_test.onnx') else real_exists(path),
    )

    response = client.post(
        '/api/models/test',
        data={
            'image': (io.BytesIO(jpeg_bytes()), 'sample.jpg'),
            'model_ids': str(model_id),
            'image_size': '320',
            'resize_mode': 'stretch',
            'conf_threshold': '0.31',
            'iou_threshold': '0.47',
            'ioh_threshold': '0.58',
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    assert captured['kwargs'] == {
        'conf_threshold': pytest.approx(0.31),
        'iou_threshold': pytest.approx(0.47),
        'ioh_threshold': pytest.approx(0.58),
        'image_size': 320,
        'resize_mode': 'stretch',
    }
    payload = response.get_json()[str(model_id)]
    assert payload['success'] is True
    assert payload['image_size'] == 320
    assert payload['resize_mode'] == 'stretch'


def test_models_experiment_template_contains_three_model_controls():
    html = Path(__file__).resolve().parents[1].joinpath(
        'templates',
        'models_experiment.html',
    ).read_text(encoding='utf-8')

    for expected in (
        'id="selectedModelsCount"',
        'id="param-image-size"',
        'id="param-resize-mode"',
        'id="param-confidence"',
        'id="param-iou"',
        'id="param-ioh"',
        "formData.append('image_size', imageSize)",
        "formData.append('resize_mode', resizeMode)",
        'checked.length > 3',
    ):
        assert expected in html
