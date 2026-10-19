import codecs
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from genie_copilot.integrations.s3 import S3Store, decode_log
from tests.helpers import BUCKET


def test_list_since_watermark_sorted_and_paginated(s3) -> None:  # type: ignore[no-untyped-def]
    t0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for i, key in enumerate(["logs/bot-a/c.log", "logs/bot-a/a.log", "logs/bot-a/b.log"]):
        with freeze_time(t0 + timedelta(minutes=i)):
            s3.put_object(Bucket=BUCKET, Key=key, Body=b"x")
    s3.put_object(Bucket=BUCKET, Key="other/z.log", Body=b"x")
    store = S3Store(BUCKET, s3)

    everything = store.list_since("logs/", None, page_size=2)
    assert [o.key for o in everything] == [
        "logs/bot-a/c.log",
        "logs/bot-a/a.log",
        "logs/bot-a/b.log",
    ]
    assert everything[0].last_modified.tzinfo is not None

    newer = store.list_since("logs/", t0 + timedelta(minutes=1))
    assert [o.key for o in newer] == ["logs/bot-a/a.log", "logs/bot-a/b.log"]  # >= watermark


def test_get_text_and_size_cap(s3) -> None:  # type: ignore[no-untyped-def]
    s3.put_object(Bucket=BUCKET, Key="k.log", Body="héllo\nwörld".encode())
    store = S3Store(BUCKET, s3)
    assert store.get_text("k.log") == "héllo\nwörld"
    assert store.get_bytes("k.log", max_bytes=3) == b"h\xc3\xa9"


def test_presigned_url(s3) -> None:  # type: ignore[no-untyped-def]
    url = S3Store(BUCKET, s3).presigned_url("logs/bot-a/a.log")
    assert ("logs/bot-a/a.log" in url and "Expires=" in url) or "X-Amz-Expires" in url


def test_decode_log_handles_boms_and_bad_bytes() -> None:
    assert decode_log(codecs.BOM_UTF8 + b"abc") == "abc"
    assert decode_log("abc".encode("utf-16")) == "abc"
    assert decode_log(b"ok \xff") == "ok \ufffd"
