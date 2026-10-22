"""Plan or reconcile narrowly scoped Lakekeeper 0.13.3 warehouse grants."""

import argparse
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID

WORKER = "kubernetes~system:serviceaccount:openings-research:openings-worker"
READER = "kubernetes~system:serviceaccount:openings-query:trino"
DESIRED = {(WORKER, "create"), (WORKER, "modify"), (READER, "select")}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ManagementClient:
    def __init__(self, origin, token_file, ca_file):
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("Management origin must be HTTPS without credentials or a path")
        self.origin = origin.rstrip("/")
        self.token_file = Path(token_file)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(),
                                  HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)))

    def request(self, method, path, body=None):
        token = self.token_file.read_text().strip()
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Invalid projected token")
        request = Request(self.origin + path, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RuntimeError("Management response exceeds limit")
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            raise RuntimeError(f"Management request failed with HTTP {error.code}") from None
        except URLError:
            raise RuntimeError("Management endpoint unavailable") from None


def plan(assignments):
    current = set()
    for item in assignments:
        if item.get("user") in (WORKER, READER):
            if set(item) != {"user", "type"} or not isinstance(item["type"], str):
                raise ValueError("Unexpected runtime assignment shape; refusing to reconcile")
            current.add((item["user"], item["type"]))
    def rows(items):
        return [{"user": user, "type": grant} for user, grant in sorted(items)]
    return {"writes": rows(DESIRED - current), "deletes": rows(current - DESIRED)}


def reconcile(client, warehouse_id, apply=False):
    warehouse_id = str(UUID(warehouse_id))
    base = "/management/v1/permissions/warehouse/" + warehouse_id
    properties = client.request("GET", base)
    if not isinstance(properties.get("managed-access"), bool):
        raise ValueError("Missing managed-access property; refusing to reconcile")
    current = client.request("GET", base + "/assignments")
    changes = plan(current["assignments"])
    report = {"warehouse-id": warehouse_id, "enable-managed-access": not properties["managed-access"],
              **changes, "applied": False}
    if not apply:
        return report
    # Enable inherited access governance before granting runtime privileges.
    if report["enable-managed-access"]:
        client.request("POST", base + "/managed-access", {"managed-access": True})
    if changes["writes"] or changes["deletes"]:
        client.request("POST", base + "/assignments", changes)
    after = client.request("GET", base + "/assignments")
    remaining = plan(after["assignments"])
    if any(remaining.values()) or client.request("GET", base)["managed-access"] is not True:
        raise RuntimeError("Grant verification failed; inspect state before retrying")
    return {**report, "applied": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Apply and verify the plan; default is read-only")
    args = parser.parse_args()
    client = ManagementClient(args.origin, args.token_file, args.ca_file)
    print(json.dumps(reconcile(client, args.warehouse_id, args.apply), indent=2))


if __name__ == "__main__":
    main()
