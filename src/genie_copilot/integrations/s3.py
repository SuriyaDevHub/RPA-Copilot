"""S3 access for Genie logs: list new objects since a watermark, read text, presign links."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
PRESIGN_SECONDS = 900


@dataclass(frozen=True)
class S3Object:
    key: str
    last_modified: datetime
    size: int


class S3Store:
    def __init__(self, bucket: str, client: Any | None = None) -> None:
        self.bucket = bucket
        self._s3 = client or boto3.client("s3")

    def list_since(
        self, prefix: str, watermark: datetime | None, page_size: int = 1000
    ) -> list[S3Object]:
        """Objects under `prefix` modified at or after `watermark`, oldest first.

        `>=` because LastModified has one-second precision: an object written in the same
        second as the last poll would otherwise be missed. Callers dedupe on the key.
        """
        paginator = self._s3.get_paginator("list_objects_v2")
        found: list[S3Object] = []
        pages = paginator.paginate(
            Bucket=self.bucket, Prefix=prefix, PaginationConfig={"PageSize": page_size}
        )
        for page in pages:
            for item in page.get("Contents", []):
                modified = item["LastModified"].astimezone(UTC)
                if watermark is None or modified >= watermark:
                    found.append(S3Object(item["Key"], modified, int(item["Size"])))
        return sorted(found, key=lambda o: (o.last_modified, o.key))

    def get_bytes(self, key: str, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
        response = self._s3.get_object(
            Bucket=self.bucket, Key=key, Range=f"bytes=0-{max_bytes - 1}"
        )
        data: bytes = response["Body"].read()
        return data

    def get_text(self, key: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
        return decode_log(self.get_bytes(key, max_bytes))

    def presigned_url(self, key: str, expires_s: int = PRESIGN_SECONDS) -> str:
        url: str = self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )
        return url


def decode_log(data: bytes) -> str:
    """.NET tools often write UTF-8 with a BOM or UTF-16; never fail on bad bytes."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")
