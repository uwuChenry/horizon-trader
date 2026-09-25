import gzip
import io
from datetime import date

import pandas as pd
import pytest

from horizon_trader.data import massive

# 2024-03-01 09:30 and 09:31 America/New_York (14:30 UTC), in Unix nanoseconds
T0 = 1709303400 * 10**9
T1 = T0 + 60 * 10**9


def _csv_gz(rows: list[tuple]) -> bytes:
    header = "ticker,volume,open,close,high,low,window_start,transactions\n"
    body = "".join(",".join(map(str, r)) + "\n" for r in rows)
    return gzip.compress((header + body).encode())


class FakeS3:
    """Just enough of boto3's S3 client: paged listing and get_object."""

    def __init__(self, objects: dict[str, bytes], page_size: int = 2):
        self.objects, self.page_size, self.gets = objects, page_size, []

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        i = int(ContinuationToken or 0)
        page = {"Contents": [{"Key": k} for k in keys[i : i + self.page_size]]}
        if i + self.page_size < len(keys):
            page |= {"IsTruncated": True, "NextContinuationToken": str(i + self.page_size)}
        return page

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))


def _server() -> FakeS3:
    rows = [("MSFT", 1975, 276.75, 275.52, 276.75, 275.25, T1, 83),
            ("MSFT", 2349, 275.2, 274.46, 275.2, 274.46, T0, 99),
            ("NA", 10, 5.0, 5.1, 5.1, 5.0, T0, 1)]  # fmt: skip
    days = ["2024-02-29", "2024-03-01", "2024-03-04", "2025-01-02"]
    return FakeS3({massive._key("minute", date.fromisoformat(d)): _csv_gz(rows) for d in days})


def test_parse_csv_converts_to_new_york_time_and_sorts():
    df = massive.parse_csv(_server().objects[massive._key("minute", date(2024, 3, 1))])
    assert list(df.columns) == [
        "ts",
        "ticker",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "transactions",
    ]
    msft = df[df.ticker == "MSFT"]
    assert [t.strftime("%H:%M") for t in msft.ts] == [
        "09:30",
        "09:31",
    ]  # sorted, 14:30 UTC -> 9:30 ET
    assert str(msft.ts.dt.tz) == "America/New_York"
    assert "NA" in set(df.ticker)  # a ticker named NA must not become NaN


def test_remote_days_pages_and_filters_by_date():
    days = massive.remote_days(_server(), "minute", date(2024, 3, 1), date(2025, 1, 2))
    assert days == [date(2024, 3, 1), date(2024, 3, 4), date(2025, 1, 2)]


def test_download_writes_parquet_and_resumes():
    server = _server()
    done, failed = massive.download(server, "minute", date(2024, 1, 1), date(2024, 12, 31))
    assert failed == {} and done == [date(2024, 2, 29), date(2024, 3, 1), date(2024, 3, 4)]
    assert massive.local_days("minute") == done

    day = massive.load_day(date(2024, 3, 1), tickers=["MSFT"])
    assert set(day.ticker) == {"MSFT"} and day.volume.sum() == 1975 + 2349

    server.gets.clear()
    done, _ = massive.download(server, "minute", date(2024, 1, 1), date(2024, 12, 31))
    assert done == [] and server.gets == []  # nothing re-downloaded


def test_download_reports_failures_and_leaves_no_partial_file():
    server = _server()
    server.objects[massive._key("minute", date(2024, 3, 4))] = b"not gzip"
    done, failed = massive.download(server, "minute", date(2024, 3, 1), date(2024, 3, 4))
    assert done == [date(2024, 3, 1)] and list(failed) == [date(2024, 3, 4)]
    assert not massive.local_path("minute", date(2024, 3, 4)).exists()
    assert not list(massive.local_path("minute", date(2024, 3, 4)).parent.glob("*.tmp"))


def test_missing_credentials_exit(monkeypatch):
    monkeypatch.delenv("MASSIVE_S3_ACCESS_KEY", raising=False)
    monkeypatch.setenv("MASSIVE_S3_SECRET_KEY", "")
    with pytest.raises(SystemExit, match="MASSIVE_S3_ACCESS_KEY"):
        massive.s3_client()


def test_load_day_roundtrip_dtypes():
    massive.download(_server(), "minute", date(2024, 3, 1), date(2024, 3, 1))
    df = massive.load_day(date(2024, 3, 1))
    assert pd.api.types.is_datetime64_any_dtype(df.ts) and len(df) == 3
