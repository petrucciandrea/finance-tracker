"""CSV import: a bad file or a bad row must degrade into a clear answer, never a 500."""

import pytest
from fastapi.testclient import TestClient

from app.services import csv_import

HEADER = "date,amount,currency,description\n"


@pytest.fixture
def account(client: TestClient, registered_user: dict) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"name": "Main checking", "type": "checking", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, registered_user: dict, account: dict, content: bytes):
    return client.post(
        f"/api/v1/transactions/import?account_id={account['id']}",
        files={"file": ("export.csv", content, "text/csv")},
        headers=registered_user["auth_headers"],
    )


def _rows(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return response.json()["rows"]


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "1E+99999", "99999999999"])
def test_out_of_range_amounts_are_flagged_per_row(
    client: TestClient, registered_user: dict, account: dict, amount: str
) -> None:
    content = f"{HEADER}2026-01-05,{amount},EUR,x\n2026-01-06,10.00,EUR,ok\n".encode()

    rows = _rows(_upload(client, registered_user, account, content))

    assert rows[0]["is_parsable"] is False
    assert rows[1]["is_parsable"] is True


def test_unknown_or_malformed_currency_is_flagged(
    client: TestClient, registered_user: dict, account: dict
) -> None:
    content = f"{HEADER}2026-01-05,1,ZZZ,x\n2026-01-05,1,EURO,x\n2026-01-05,1,EUR,ok\n".encode()

    rows = _rows(_upload(client, registered_user, account, content))

    assert [r["is_parsable"] for r in rows] == [False, False, True]


def test_non_utf8_file_is_a_422_not_a_500(
    client: TestClient, registered_user: dict, account: dict
) -> None:
    response = _upload(client, registered_user, account, b"\xff\xfe\x00bad")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CSV_IMPORT_ERROR"


def test_oversized_file_is_rejected(
    client: TestClient, registered_user: dict, account: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_import, "MAX_CSV_BYTES", 100)

    body = (HEADER + "2026-01-05,1,EUR,x\n" * 20).encode()

    response = _upload(client, registered_user, account, body)

    assert response.status_code == 422
    assert "too large" in response.json()["error"]["message"]


def test_too_many_rows_are_rejected(
    client: TestClient, registered_user: dict, account: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(csv_import, "MAX_CSV_ROWS", 3)

    body = (HEADER + "2026-01-05,1,EUR,x\n" * 4).encode()

    response = _upload(client, registered_user, account, body)

    assert response.status_code == 422
    assert "Too many rows" in response.json()["error"]["message"]


def test_expired_previews_are_evicted_on_the_next_upload(
    client: TestClient, registered_user: dict, account: dict
) -> None:
    from datetime import UTC, datetime, timedelta

    content = f"{HEADER}2026-01-05,1,EUR,x\n".encode()
    first = _upload(client, registered_user, account, content).json()["import_id"]
    for preview in csv_import._preview_store.values():
        preview.created_at = datetime.now(UTC) - timedelta(hours=1)

    _upload(client, registered_user, account, content)

    assert first not in {str(k) for k in csv_import._preview_store}


def test_asset_symbol_with_path_characters_is_flagged(
    client: TestClient, registered_user: dict
) -> None:
    broker = client.post(
        "/api/v1/accounts",
        json={"name": "Broker", "type": "investment", "currency": "EUR"},
        headers=registered_user["auth_headers"],
    ).json()
    content = (
        b"symbol,asset_type,type,quantity,price,date\n"
        b"../../etc,stock,buy,1,10,2026-01-05\n"
        b"AAPL,stock,buy,1,10,2026-01-05\n"
    )

    response = client.post(
        f"/api/v1/portfolio/transactions/import?account_id={broker['id']}",
        files={"file": ("a.csv", content, "text/csv")},
        headers=registered_user["auth_headers"],
    )

    assert [r["is_parsable"] for r in _rows(response)] == [False, True]
