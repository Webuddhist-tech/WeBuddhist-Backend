import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi import UploadFile, HTTPException, status
from pecha_api.image_utils import ImageUtils
from pecha_api.sheets.sheets_service import upload_sheet_image_request


def test_validate_and_compress_image_success():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.image_utils.get_int", side_effect=[5, 75]), \
            patch("PIL.Image.open") as mock_open:
        mock_image = MagicMock()
        mock_image.mode = 'RGB'  # Set the mode to RGB
        mock_open.return_value = mock_image
        mock_image.save = MagicMock()

        image_utils = ImageUtils()
        compressed_image = image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
        assert isinstance(compressed_image, io.BytesIO)
        mock_image.save.assert_called_once_with(compressed_image, format="WEBP", quality=75)


def test_validate_and_compress_image_invalid_file_type():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.txt", file=file_content)
    try:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="text/plain")
    except HTTPException as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
        assert e.detail == 'Only image files are allowed'


def test_validate_and_compress_image_file_too_large():
    file_content = io.BytesIO(b"fake_image_data" * 1024 * 1024 * 6)  # 6 MB
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.config.get_int", return_value=5), \
            pytest.raises(HTTPException) as exc_info:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "File size exceeds 1MB limit"


def test_validate_and_compress_image_processing_failure():
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)

    with patch("pecha_api.config.get_int", side_effect=[5, 75]), \
            pytest.raises(HTTPException) as exc_info:
        image_utils = ImageUtils()
        image_utils.validate_and_compress_image(file=file, content_type="image/jpeg")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to process the image"


def test_upload_sheet_image_request_with_sheet_id():
    #Test uploading sheet image with sheet ID#
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)
    # Create a mock file with content_type since the property is read-only
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.jpg"
    mock_file.file = file_content
    mock_file.content_type = "image/jpeg"
    
    sheet_id = "test_sheet_id"
    
    with patch("pecha_api.sheets.sheets_service.ImageUtils.validate_and_compress_image") as mock_validate, \
         patch("pecha_api.sheets.sheets_service.upload_bytes", return_value="test_upload_key") as mock_upload, \
         patch("pecha_api.sheets.sheets_service.generate_presigned_access_url", return_value="https://test-url.com") as mock_presigned, \
         patch("pecha_api.sheets.sheets_service.get", return_value="test-bucket"):
        
        mock_validate.return_value = io.BytesIO(b"compressed_image_data")
        
        result = upload_sheet_image_request(sheet_id=sheet_id, file=mock_file)
        
        assert result.url == "https://test-url.com"
        assert result.key == "test_upload_key"
        mock_validate.assert_called_once()
        mock_upload.assert_called_once()
        mock_presigned.assert_called_once()


def test_upload_sheet_image_request_without_sheet_id():
    #Test uploading sheet image without sheet ID#
    file_content = io.BytesIO(b"fake_image_data")
    file = UploadFile(filename="test.jpg", file=file_content)
    # Create a mock file with content_type since the property is read-only
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.jpg"
    mock_file.file = file_content
    mock_file.content_type = "image/jpeg"
    
    with patch("pecha_api.sheets.sheets_service.ImageUtils.validate_and_compress_image") as mock_validate, \
         patch("pecha_api.sheets.sheets_service.upload_bytes", return_value="test_upload_key") as mock_upload, \
         patch("pecha_api.sheets.sheets_service.generate_presigned_access_url", return_value="https://test-url.com") as mock_presigned, \
         patch("pecha_api.sheets.sheets_service.get", return_value="test-bucket"):
        
        mock_validate.return_value = io.BytesIO(b"compressed_image_data")
        
        result = upload_sheet_image_request(sheet_id=None, file=mock_file)
        
        assert result.url == "https://test-url.com"
        assert result.key == "test_upload_key"


def test_upload_sheet_image_request_validation_error():
    #Test upload_sheet_image_request when image validation fails#
    file_content = io.BytesIO(b"invalid_image_data")
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.jpg"
    mock_file.file = file_content
    mock_file.content_type = "image/jpeg"
    
    with patch("pecha_api.sheets.sheets_service.ImageUtils.validate_and_compress_image", side_effect=HTTPException(status_code=400, detail="Invalid image")):
        with pytest.raises(HTTPException) as exc_info:
            upload_sheet_image_request(sheet_id="test_id", file=mock_file)
        
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid image"

