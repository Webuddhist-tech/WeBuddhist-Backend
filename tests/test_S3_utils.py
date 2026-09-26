import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException, UploadFile
from starlette import status
from io import BytesIO
from pecha_api.uploads.S3_utils import upload_file, upload_bytes, generate_presigned_access_url, delete_file, download_bytes


@pytest.fixture
def mock_s3_client():
    with patch("pecha_api.uploads.S3_utils.s3_client") as mock:
        yield mock


@pytest.fixture
def upload_file_mock():
    file = MagicMock(spec=UploadFile)
    file.file = BytesIO(b"test data")
    file.content_type = "text/plain"
    return file


def test_upload_file_success(mock_s3_client, upload_file_mock):
    mock_s3_client.upload_fileobj.return_value = None
    result = upload_file("test-bucket", "test-key", upload_file_mock)
    assert result == "test-key"


def test_upload_file_client_error(mock_s3_client, upload_file_mock):
    mock_s3_client.upload_fileobj.side_effect = Exception("ClientError")
    with pytest.raises(Exception):
        upload_file("test-bucket", "test-key", upload_file_mock)


def test_upload_bytes_success(mock_s3_client):
    file = BytesIO(b"test data")
    result = upload_bytes("test-bucket", "test-key", file, "text/plain")
    assert result == "test-key"


def test_upload_bytes_invalid_file(mock_s3_client):
    with pytest.raises(Exception):
        upload_bytes("test-bucket", "test-key", "invalid file", "text/plain")


def test_generate_presigned_access_url_success(mock_s3_client):
    mock_s3_client.generate_presigned_url.return_value = "http://example.com"
    result = generate_presigned_access_url("test-bucket", "test-key")
    assert result == "http://example.com"


def test_generate_presigned_access_url_client_error(mock_s3_client):
    mock_s3_client.generate_presigned_url.side_effect = Exception("ClientError")
    with pytest.raises(Exception):
        generate_presigned_access_url("test-bucket", "test-key")


def test_delete_file_success(mock_s3_client):
    mock_s3_client.delete_object.return_value = None
    result = delete_file("test-key")
    assert result is True


def test_delete_file_client_error(mock_s3_client):
    mock_s3_client.delete_object.side_effect = mock_s3_client.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "DeleteObject"
    )
    result = delete_file("test-key")
    assert result is True


def test_delete_file_unexpected_error(mock_s3_client):
    mock_s3_client.delete_object.side_effect = Exception("UnexpectedError")
    with pytest.raises(Exception):
        delete_file("test-key")


class _TrackedBody:
    """A stand-in for the streaming body `get_object` returns, which holds a
    connection until it is closed."""

    def __init__(self, payload: bytes):
        self._stream = BytesIO(payload)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size) if size and size >= 0 else self._stream.read()

    def close(self) -> None:
        self.closed = True


def _get_object(mock_s3_client, payload: bytes, content_length=None) -> _TrackedBody:
    body = _TrackedBody(payload)
    mock_s3_client.get_object.return_value = {
        "Body": body,
        **({} if content_length is None else {"ContentLength": content_length}),
    }
    return body


def test_download_bytes_returns_the_object(mock_s3_client):
    body = _get_object(mock_s3_client, b"photo")
    assert download_bytes("bucket", "key") == b"photo"
    assert body.closed


def test_download_bytes_closes_the_body_when_content_length_is_too_large(mock_s3_client):
    """The rejection is reached before the body is read, so nothing else
    returns its connection to the pool - and a public preview endpoint can be
    made to take this path on every hit."""
    body = _get_object(mock_s3_client, b"x" * 50, content_length=50)
    with pytest.raises(HTTPException) as error:
        download_bytes("bucket", "key", max_bytes=10)
    assert error.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert body.closed


def test_download_bytes_closes_the_body_when_the_content_length_lied(mock_s3_client):
    """A missing or understated ContentLength is caught by the read instead,
    which leaves the body half-consumed rather than exhausted."""
    body = _get_object(mock_s3_client, b"x" * 50)
    with pytest.raises(HTTPException) as error:
        download_bytes("bucket", "key", max_bytes=10)
    assert error.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert body.closed


def test_download_bytes_within_the_limit_is_returned_and_closed(mock_s3_client):
    body = _get_object(mock_s3_client, b"small", content_length=5)
    assert download_bytes("bucket", "key", max_bytes=10) == b"small"
    assert body.closed

