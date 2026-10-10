"""Routes whose data lived in MongoDB stay mounted, deprecated, and answer as
an empty store would until their callers are removed."""
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api

client = TestClient(api)
AUTH = {"Authorization": "Bearer dummy"}


def test_sheets_list_is_empty():
    response = client.get("/api/v1/sheets", params={"skip": 5, "limit": 3})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"sheets": [], "skip": 5, "limit": 3, "total": 0}


def test_sheet_detail_is_not_found():
    assert client.get("/api/v1/sheets/abc").status_code == status.HTTP_404_NOT_FOUND


def test_sheet_delete_is_not_found():
    assert client.delete("/api/v1/sheets/abc", headers=AUTH).status_code == status.HTTP_404_NOT_FOUND


def test_sheet_writes_are_gone():
    sheet = {"title": "t", "source": [], "is_published": False}

    assert client.post("/api/v1/sheets", json=sheet, headers=AUTH).status_code == status.HTTP_410_GONE
    assert client.put("/api/v1/sheets/abc", json=sheet, headers=AUTH).status_code == status.HTTP_410_GONE


def test_mappings_are_gone():
    payload = {"text_mappings": []}

    assert client.post("/api/v1/mappings", json=payload, headers=AUTH).status_code == status.HTTP_410_GONE
    assert client.request("DELETE", "/api/v1/mappings", json=payload, headers=AUTH).status_code == status.HTTP_410_GONE


def test_text_uploader_list_is_empty():
    response = client.post("/api/v1/text-uploader/list", json={"pecha_text_ids": ["a", "b"]})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_text_uploader_collection_is_null():
    response = client.get("/api/v1/text-uploader/collections/abc")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() is None


def test_routes_are_marked_deprecated():
    schema = api.openapi()["paths"]
    for path, method in [
        ("/sheets", "get"),
        ("/sheets", "post"),
        ("/sheets/{sheet_id}", "get"),
        ("/mappings", "post"),
        ("/segments/search", "post"),
        ("/text-uploader/list", "post"),
        ("/text-uploader/collections/{pecha_collection_id}", "get"),
    ]:
        assert schema[path][method].get("deprecated") is True, (path, method)
