from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from openings_research.catalog_proxy import CatalogBridge, create_app


class Reply(BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}


def test_rotated_token_is_read_on_every_request_and_client_headers_are_not_forwarded(tmp_path):
    token = tmp_path / "token"
    calls = []

    def send(request, timeout):
        calls.append(request)
        return Reply(b'{}')

    client = TestClient(create_app(CatalogBridge("https://catalog.svc:8443", token,
                                                SimpleNamespace(open=send))))
    for value in ("first", "rotated"):
        token.write_text(value)
        response = client.get("/catalog/v1/config", headers={"Authorization": "Bearer attacker",
                                                           "Host": "attacker.invalid"})
        assert response.status_code == 200
        assert calls[-1].get_header("Authorization") == "Bearer " + value
        assert calls[-1].full_url == "https://catalog.svc:8443/catalog/v1/config"
        assert calls[-1].get_header("Host") is None


@pytest.mark.parametrize("method,path", [("GET", "/management/v1/warehouse"),
                                         ("DELETE", "/catalog/v1/namespaces"),
                                         ("GET", "/catalog/../management"),
                                         ("GET", "/catalog/%2e%2e/management")])
def test_bridge_denies_management_paths_and_mutating_verbs(tmp_path, method, path):
    bridge = CatalogBridge("https://catalog.svc", tmp_path / "absent", None)
    assert bridge.forward(method, path, {}, b"")[0] == 403


def test_errors_do_not_expose_token_or_upstream(tmp_path):
    client = TestClient(create_app(CatalogBridge("https://private-catalog.svc", tmp_path / "missing", None)))
    result = client.get("/catalog/v1/config")
    assert result.status_code == 502
    assert result.text == "Catalog unavailable"


def test_bridge_does_not_follow_redirects_or_return_location(tmp_path):
    token = tmp_path / "token"
    token.write_text("private")
    response = Reply(b"")
    response.status = 302
    response.headers = {"Location": "https://other.invalid"}
    bridge = CatalogBridge("https://catalog.svc", token,
                           SimpleNamespace(open=lambda *args, **kwargs: response))
    result = TestClient(create_app(bridge)).get("/catalog/v1/config")
    assert result.status_code == 502
    assert "location" not in result.headers
