from pathlib import Path

import pytest

from artifact_object_store import (
    DisabledObjectStore,
    ObjectStoreError,
    S3CompatibleObjectStore,
    object_store_from_config,
)


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append((operation, Params, ExpiresIn))
        return f"https://objects.example/{operation}/{Params['Key']}"

    def head_object(self, Bucket, Key):
        self.calls.append(('head_object', Bucket, Key))
        return {
            'ContentLength': 123,
            'ETag': '"etag-value"',
            'Metadata': {'kind': 'checkpoint'},
        }

    def upload_file(self, source, bucket, key):
        self.calls.append(('upload_file', source, bucket, key))

    def download_file(self, bucket, key, destination):
        self.calls.append(('download_file', bucket, key, destination))
        Path(destination).write_bytes(b'checkpoint')

    def delete_object(self, Bucket, Key):
        self.calls.append(('delete_object', Bucket, Key))


def make_store(client=None):
    return S3CompatibleObjectStore(
        endpoint_url='https://account.r2.cloudflarestorage.com',
        bucket='toolib-training',
        region='auto',
        access_key_id='access-key',
        secret_access_key='secret-key',
        prefix='toolib',
        presign_seconds=604800,
        client=client or FakeS3Client(),
    )


def test_s3_store_generates_scoped_presigned_urls_and_metadata(tmp_path):
    client = FakeS3Client()
    store = make_store(client)
    object_key = store.object_key(
        'training',
        'task-id',
        'checkpoints',
        'epoch-0005.pt',
    )

    assert object_key == (
        'toolib/training/task-id/checkpoints/epoch-0005.pt'
    )
    assert store.presign_upload(object_key).startswith('https://objects.example/')
    assert store.presign_download(object_key).startswith('https://objects.example/')
    metadata = store.head(object_key)
    assert metadata.size_bytes == 123
    assert metadata.etag == 'etag-value'
    assert metadata.metadata == {'kind': 'checkpoint'}

    source = tmp_path / 'last.pt'
    source.write_bytes(b'checkpoint')
    store.upload_file(source, object_key)
    destination = tmp_path / 'downloaded.pt'
    store.download_file(object_key, destination)
    assert destination.read_bytes() == b'checkpoint'
    store.delete(object_key)


@pytest.mark.parametrize(
    'unsafe_value',
    (
        '../outside.pt',
        'training/../../outside.pt',
        '/absolute.pt',
    ),
)
def test_s3_store_rejects_unsafe_object_keys(unsafe_value):
    store = make_store()

    with pytest.raises(ObjectStoreError):
        store.object_key(unsafe_value)


def test_disabled_store_is_default_and_requires_no_cloud_dependency():
    store = object_store_from_config({})

    assert isinstance(store, DisabledObjectStore)
    assert store.enabled is False
    with pytest.raises(ObjectStoreError):
        store.require_enabled()
