import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional


class ObjectStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    size_bytes: int
    etag: Optional[str] = None
    metadata: Optional[dict] = None


class DisabledObjectStore:
    backend_name = 'disabled'
    enabled = False

    def require_enabled(self):
        raise ObjectStoreError(
            'Object storage is disabled. Configure '
            'TOOLIB_OBJECT_STORE_BACKEND=s3 to enable resumable checkpoints.'
        )


class S3CompatibleObjectStore:
    backend_name = 's3'
    enabled = True

    def __init__(
        self,
        *,
        endpoint_url,
        bucket,
        region,
        access_key_id,
        secret_access_key,
        prefix='toolib',
        presign_seconds=604800,
        client=None,
    ):
        if not endpoint_url:
            raise ObjectStoreError('TOOLIB_OBJECT_STORE_ENDPOINT is required.')
        if not bucket:
            raise ObjectStoreError('TOOLIB_OBJECT_STORE_BUCKET is required.')
        if not access_key_id or not secret_access_key:
            raise ObjectStoreError(
                'Object storage access key and secret key are required.'
            )
        self.endpoint_url = str(endpoint_url).rstrip('/')
        self.bucket = str(bucket).strip()
        self.region = str(region or 'auto').strip() or 'auto'
        self.prefix = self._normalize_prefix(prefix)
        self.presign_seconds = max(60, min(int(presign_seconds), 604800))
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise ObjectStoreError(
                    'boto3 is required when TOOLIB_OBJECT_STORE_BACKEND=s3.'
                ) from exc
            client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                region_name=self.region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 5, 'mode': 'standard'},
                ),
            )
        self.client = client

    @staticmethod
    def _normalize_prefix(value):
        value = str(value or '').strip().replace('\\', '/')
        if value.startswith('/'):
            raise ObjectStoreError('Object storage prefix is invalid.')
        value = value.strip('/')
        if not value:
            return ''
        path = PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts:
            raise ObjectStoreError('Object storage prefix is invalid.')
        return str(path)

    def object_key(self, *parts):
        normalized_parts = []
        for raw_part in parts:
            value = str(raw_part or '').strip().replace('\\', '/')
            if value.startswith('/'):
                raise ObjectStoreError('Object key contains an unsafe path.')
            value = value.strip('/')
            if not value:
                continue
            path = PurePosixPath(value)
            if path.is_absolute() or '..' in path.parts:
                raise ObjectStoreError('Object key contains an unsafe path.')
            normalized_parts.extend(path.parts)
        if not normalized_parts:
            raise ObjectStoreError('Object key cannot be empty.')
        key = '/'.join(normalized_parts)
        return f'{self.prefix}/{key}' if self.prefix else key

    def presign_upload(self, object_key, *, content_type='application/octet-stream'):
        return self.client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self.bucket,
                'Key': self._require_key(object_key),
                'ContentType': content_type,
            },
            ExpiresIn=self.presign_seconds,
        )

    def presign_download(self, object_key):
        return self.client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket,
                'Key': self._require_key(object_key),
            },
            ExpiresIn=self.presign_seconds,
        )

    def head(self, object_key):
        key = self._require_key(object_key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ObjectStoreError(
                f'Could not inspect object {key}: {exc}'
            ) from exc
        return StoredObject(
            object_key=key,
            size_bytes=int(response.get('ContentLength') or 0),
            etag=str(response.get('ETag') or '').strip('"') or None,
            metadata=dict(response.get('Metadata') or {}),
        )

    def upload_file(self, source, object_key):
        source = Path(source).resolve()
        if not source.is_file():
            raise ObjectStoreError(f'Upload source does not exist: {source}')
        key = self._require_key(object_key)
        try:
            self.client.upload_file(str(source), self.bucket, key)
        except Exception as exc:
            raise ObjectStoreError(f'Could not upload object {key}: {exc}') from exc
        return self.head(key)

    def download_file(self, object_key, destination):
        key = self._require_key(object_key)
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f'.{destination.name}.{os.getpid()}.part')
        try:
            self.client.download_file(self.bucket, key, str(temporary))
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise ObjectStoreError(
                f'Could not download object {key}: {exc}'
            ) from exc
        return destination

    def delete(self, object_key):
        key = self._require_key(object_key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ObjectStoreError(f'Could not delete object {key}: {exc}') from exc

    def _require_key(self, object_key):
        key = str(object_key or '').strip().replace('\\', '/')
        if key.startswith('/'):
            raise ObjectStoreError('Object key contains an unsafe path.')
        key = key.strip('/')
        if not key:
            raise ObjectStoreError('Object key cannot be empty.')
        path = PurePosixPath(key)
        if path.is_absolute() or '..' in path.parts:
            raise ObjectStoreError('Object key contains an unsafe path.')
        if self.prefix and not key.startswith(f'{self.prefix}/'):
            raise ObjectStoreError('Object key is outside the configured prefix.')
        return key


def object_store_from_config(config: Mapping):
    backend = str(
        config.get('TOOLIB_OBJECT_STORE_BACKEND')
        or os.environ.get('TOOLIB_OBJECT_STORE_BACKEND')
        or 'disabled'
    ).strip().lower()
    if backend in {'', 'disabled', 'none', 'local'}:
        return DisabledObjectStore()
    if backend != 's3':
        raise ObjectStoreError(
            'TOOLIB_OBJECT_STORE_BACKEND must be disabled or s3.'
        )
    return S3CompatibleObjectStore(
        endpoint_url=(
            config.get('TOOLIB_OBJECT_STORE_ENDPOINT')
            or os.environ.get('TOOLIB_OBJECT_STORE_ENDPOINT')
        ),
        bucket=(
            config.get('TOOLIB_OBJECT_STORE_BUCKET')
            or os.environ.get('TOOLIB_OBJECT_STORE_BUCKET')
        ),
        region=(
            config.get('TOOLIB_OBJECT_STORE_REGION')
            or os.environ.get('TOOLIB_OBJECT_STORE_REGION')
            or 'auto'
        ),
        access_key_id=(
            config.get('TOOLIB_OBJECT_STORE_ACCESS_KEY_ID')
            or os.environ.get('TOOLIB_OBJECT_STORE_ACCESS_KEY_ID')
        ),
        secret_access_key=(
            config.get('TOOLIB_OBJECT_STORE_SECRET_ACCESS_KEY')
            or os.environ.get('TOOLIB_OBJECT_STORE_SECRET_ACCESS_KEY')
        ),
        prefix=(
            config.get('TOOLIB_OBJECT_STORE_PREFIX')
            or os.environ.get('TOOLIB_OBJECT_STORE_PREFIX')
            or 'toolib'
        ),
        presign_seconds=(
            config.get('TOOLIB_OBJECT_STORE_PRESIGN_SECONDS')
            or os.environ.get('TOOLIB_OBJECT_STORE_PRESIGN_SECONDS')
            or 604800
        ),
    )
