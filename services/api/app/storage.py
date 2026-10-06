from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.object_storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )

    def upload_file(
        self, file: BinaryIO, object_key: str, content_type: str | None
    ) -> None:
        self._ensure_bucket()
        extra_args = {"ContentType": content_type} if content_type else {}
        self.client.upload_fileobj(file, self.bucket, object_key, ExtraArgs=extra_args)

    def delete_file(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)

    def download_file(self, object_key: str, destination: str | Path) -> None:
        self.client.download_file(self.bucket, object_key, str(destination))

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except ClientError as create_error:
                code = create_error.response.get("Error", {}).get("Code")
                if code != "BucketAlreadyOwnedByYou":
                    raise


def get_object_storage() -> ObjectStorage:
    return ObjectStorage(Settings())
