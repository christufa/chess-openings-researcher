import pytest

from openings_research.catalog_access import DESIRED, READER, WORKER, plan, reconcile

WAREHOUSE = "00000000-0000-4000-8000-000000000001"


class Catalog:
    def __init__(self, managed=False):
        self.managed = managed
        self.assignments = [{"user": READER, "type": "ownership"},
                            {"user": "oidc~operator", "type": "ownership"}]
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path.endswith("/managed-access"):
            self.managed = body["managed-access"]
        elif method == "POST":
            self.assignments = [row for row in self.assignments if row not in body["deletes"]]
            self.assignments += body["writes"]
        elif path.endswith("/assignments"):
            return {"assignments": self.assignments.copy()}
        return {"managed-access": self.managed}


def test_dry_run_never_writes_and_removes_reader_ownership():
    client = Catalog()
    result = reconcile(client, WAREHOUSE)
    assert result["deletes"] == [{"user": READER, "type": "ownership"}]
    assert not result["applied"]
    assert all(method == "GET" for method, _, _ in client.calls)


def test_apply_governs_access_first_preserves_operator_and_is_idempotent():
    client = Catalog()
    assert reconcile(client, WAREHOUSE, True)["applied"]
    mutations = [call for call in client.calls if call[0] == "POST"]
    assert mutations[0][1].endswith("/managed-access")
    assert {"user": "oidc~operator", "type": "ownership"} in client.assignments
    assert {(row["user"], row["type"]) for row in client.assignments if row["user"] in (WORKER, READER)} == DESIRED
    client.calls.clear()
    reconcile(client, WAREHOUSE, True)
    assert not any(method == "POST" for method, _, _ in client.calls)


def test_fail_closed_on_unknown_runtime_assignment_shape():
    with pytest.raises(ValueError):
        plan([{"user": WORKER, "type": "ownership", "condition": "unknown"}])


def test_verification_detects_ignored_mutation():
    class ReadOnly(Catalog):
        def request(self, method, path, body=None):
            if method == "POST":
                return {}
            return super().request(method, path, body)
    with pytest.raises(RuntimeError, match="verification"):
        reconcile(ReadOnly(), WAREHOUSE, True)


def test_management_transport_rotates_tokens_and_sanitizes_errors(tmp_path, monkeypatch):
    import io
    from urllib.error import HTTPError

    from openings_research.catalog_access import ManagementClient
    token = tmp_path / "token"
    token.write_text("first-token")
    monkeypatch.setattr("openings_research.catalog_access.ssl.create_default_context", lambda **kwargs: None)
    client = ManagementClient("https://catalog.invalid:8443", token, "fixture.pem")
    class Transport:
        def __init__(self):
            self.headers = []
        def open(self, request, timeout):
            self.headers.append(request.get_header("Authorization"))
            return io.BytesIO(b'{"ok": true}')
    transport = Transport()
    client.opener = transport
    client.request("GET", "/management/v1/permissions/warehouse/fixture")
    token.write_text("second-token")
    client.request("GET", "/management/v1/permissions/warehouse/fixture")
    assert transport.headers == ["Bearer first-token", "Bearer second-token"]
    def fail(*args, **kwargs):
        raise HTTPError("https://catalog.invalid", 403, "secret detail", {}, None)
    monkeypatch.setattr(transport, "open", fail)
    with pytest.raises(RuntimeError, match="^Management request failed with HTTP 403$"):
        client.request("GET", "/management/v1/permissions/warehouse/fixture")


def test_management_transport_rejects_credential_bearing_origin():
    from openings_research.catalog_access import ManagementClient, NoRedirect
    with pytest.raises(ValueError):
        ManagementClient("https://user:secret@catalog.invalid", "unused", "unused")
    assert NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere") is None
