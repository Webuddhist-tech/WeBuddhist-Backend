import os
import uuid
from typing import Optional

from fastapi import UploadFile

from pecha_api.config import get
from pecha_api.image_utils import ImageUtils
from .sheets_response_models import SheetImageResponse
from ..uploads.S3_utils import upload_bytes, generate_presigned_access_url


def upload_sheet_image_request(sheet_id: Optional[str], file: UploadFile) -> SheetImageResponse:
    # Validate and compress the uploaded image
    image_utils = ImageUtils()
    compressed_image = image_utils.validate_and_compress_image(file=file, content_type=file.content_type)
    file_name, _ = os.path.splitext(file.filename)
    unique_id = str(uuid.uuid4())

    # If no id is provided, use a random UUID as the folder name
    path = "images/sheet_images"
    image_path_full = f"{path}/{sheet_id}/{unique_id}" if sheet_id is not None else f"{path}/{unique_id}"
    sheet_image_name = f"{image_path_full}/{file_name}.webp"
    upload_key = upload_bytes(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=sheet_image_name,
        file=compressed_image,
        content_type="image/webp"
    )
    presigned_url = generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=upload_key
    )

    return SheetImageResponse(url=presigned_url, key=upload_key)
