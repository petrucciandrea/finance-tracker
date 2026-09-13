"""
Tests for the categories router: parent/child hierarchy, rename, moving a
subcategory between parents, and the two-level nesting cap.
"""

from fastapi.testclient import TestClient


def _create_category(
    client: TestClient, headers: dict, name: str, category_type: str, parent_id: str | None = None
) -> dict:
    payload = {"name": name, "type": category_type}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = client.post("/api/v1/categories", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_subcategory_under_parent(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    parent = _create_category(client, headers, "Food", "expense")
    child = _create_category(client, headers, "Restaurants", "expense", parent["id"])

    assert child["parent_id"] == parent["id"]


def test_subcategory_parent_must_share_type(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    parent = _create_category(client, headers, "Salary", "income")

    response = client.post(
        "/api/v1/categories",
        json={"name": "Restaurants", "type": "expense", "parent_id": parent["id"]},
        headers=headers,
    )

    assert response.status_code == 422


def test_cannot_nest_a_subcategory_under_another_subcategory(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    parent = _create_category(client, headers, "Food", "expense")
    child = _create_category(client, headers, "Restaurants", "expense", parent["id"])

    response = client.post(
        "/api/v1/categories",
        json={"name": "Fine dining", "type": "expense", "parent_id": child["id"]},
        headers=headers,
    )

    assert response.status_code == 422


def test_rename_category(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    category = _create_category(client, headers, "Food", "expense")

    response = client.patch(
        f"/api/v1/categories/{category['id']}", json={"name": "Groceries"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Groceries"


def test_move_subcategory_to_a_different_parent(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    food = _create_category(client, headers, "Food", "expense")
    leisure = _create_category(client, headers, "Leisure", "expense")
    child = _create_category(client, headers, "Streaming", "expense", food["id"])

    response = client.patch(
        f"/api/v1/categories/{child['id']}", json={"parent_id": leisure["id"]}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == leisure["id"]


def test_delete_category_with_active_subcategory_is_rejected(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    parent = _create_category(client, headers, "Food", "expense")
    _create_category(client, headers, "Restaurants", "expense", parent["id"])

    response = client.delete(f"/api/v1/categories/{parent['id']}", headers=headers)

    assert response.status_code == 409


def test_create_transfer_category(client: TestClient, registered_user: dict) -> None:
    headers = registered_user["auth_headers"]
    category = _create_category(client, headers, "Investimenti", "transfer")

    assert category["type"] == "transfer"


def test_transfer_subcategory_parent_must_share_type(
    client: TestClient, registered_user: dict
) -> None:
    headers = registered_user["auth_headers"]
    parent = _create_category(client, headers, "Investimenti", "transfer")

    response = client.post(
        "/api/v1/categories",
        json={"name": "ETF", "type": "expense", "parent_id": parent["id"]},
        headers=headers,
    )

    assert response.status_code == 422
