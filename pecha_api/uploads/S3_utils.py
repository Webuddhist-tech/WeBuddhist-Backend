from contextlib import closing
from http import HTTPMethod
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException
import logging

from starlette import status

from ..config import get, get_int

s3_client = boto3.client(
    "s3",
    aws_access_key_id=get("AWS_ACCESS_KEY"),
    aws_secret_access_key=get("AWS_SECRET_KEY"),
    region_name=get("AWS_REGION")

)


def upload_file(bucket_name: str, s3_key: str, file: UploadFile) -> str:
    try:
        s3_client.upload_fileobj(
            Fileobj=file.file,
            Bucket=bucket_name,
            Key=s3_key,
            ExtraArgs={
                "ContentType": file.content_type,
                "ExpectedBucketOwner": get("AWS_BUCKET_OWNER")
            }
        )
        return s3_key
    except ClientError as e:
        logging.error(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to upload file to S3.")
    except Exception as e:
        logging.error(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An unexpected error occurred.")


def upload_bytes(bucket_name: str, s3_key: str, file: BytesIO, content_type: str) -> str:
    try:
        if not isinstance(file, BytesIO):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="The 'file' parameter must be a BytesIO object")
        s3_client.upload_fileobj(
            Fileobj=file,
            Bucket=bucket_name,
            Key=s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "ExpectedBucketOwner": get("AWS_BUCKET_OWNER")
            }
        )
        return s3_key
    except ClientError as e:
        logging.error(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to upload file to S3.")
    except Exception as e:
        logging.error(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An unexpected error occurred.")


# AWS refuses a SigV4 signature asked to live longer than a week.
MAX_PRESIGNED_EXPIRY_SECONDS = 7 * 24 * 60 * 60


def presigned_url_expiry_seconds() -> int:
    """Lifetime to sign read URLs with, clamped to what AWS will accept.

    These URLs are handed out inside responses the API caches, so the
    signature has to outlive the cache entry carrying it - see
    `pecha_api.cache.presigned_expiry`, which holds the other half of that
    bargain by refusing to keep an entry longer than its signatures last.
    """
    return min(get_int("PRESIGNED_URL_EXPIRY_SECONDS"), MAX_PRESIGNED_EXPIRY_SECONDS)


def generate_presigned_access_url(bucket_name: str, s3_key: str):
    if isinstance(s3_key, str) and s3_key.strip():
        # Generate a presigned URL for uploading an object
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": bucket_name,
                "Key": s3_key
            },
            ExpiresIn=presigned_url_expiry_seconds()
        )
        return presigned_url
    return ""


def download_bytes(bucket_name: str, s3_key: str, max_bytes: int | None = None) -> bytes:
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key, ExpectedBucketOwner=get("AWS_BUCKET_OWNER"))
        # `Body` is a streaming socket, not bytes: both size rejections below
        # leave it unread, and a partial read leaves it half-consumed, so
        # neither returns its connection to the pool on its own. Closing is the
        # only thing that does, and the rejected paths are the ones a public
        # preview endpoint can be made to take over and over.
        with closing(response["Body"]) as body_stream:
            if max_bytes is not None:
                # Checked before the read, so an object larger than the caller
                # can afford costs a HEAD-sized response rather than being
                # pulled into memory in full and then rejected.
                length = response.get("ContentLength")
                if length is not None and length > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Object is larger than the caller allows.",
                    )
                # One byte past the limit, so a missing or lying ContentLength
                # is still caught rather than trusted.
                body = body_stream.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Object is larger than the caller allows.",
                    )
                return body
            return body_stream.read()
    except ClientError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to download file from S3.")


def delete_file(file_path: str):
    try:
        s3_client.delete_object(
            Bucket=get("AWS_BUCKET_NAME"), 
            Key=file_path,
            ExpectedBucketOwner=get("AWS_BUCKET_OWNER")
        )
        return True
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        # NoSuchKey is fine - file already doesn't exist
        # 404 and NotFound are also acceptable
        if error_code in ('NoSuchKey', '404', 'NotFound'):
            return False
        logging.error(f"S3 delete error for {file_path}: {error_code} - {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error deleting file.")
    except Exception as e:
        logging.error(f"Unexpected error deleting {file_path}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error deleting file.")
