"""Exercise the rendered Trino configuration against real TLS and JWT authentication."""

import base64
import json
import os
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".databricks/platform-validation"
ISSUER = "https://host.docker.internal:18443/"
NAME = "openings-trino-platform-test"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs).stdout


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for directory in ("config", "catalog", "access", "tls", "ca"):
        (WORK / directory).mkdir(exist_ok=True)
    for directory in ("catalog", "access", "tls", "ca"):
        (WORK / "config" / directory).mkdir(exist_ok=True)
    key = WORK / "tls/key.pem"
    cert = WORK / "tls/cert.pem"
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost,DNS:host.docker.internal,DNS:trino.openings-query.svc.cluster.local")
    (WORK / "tls/tls-combined.pem").write_bytes(key.read_bytes() + cert.read_bytes())
    (WORK / "ca/ca.crt").write_bytes(cert.read_bytes())
    # Create the Java trust store with the exact JDK used by Trino.
    truststore = WORK / "ca/truststore.jks"
    if truststore.exists():
        truststore.unlink()
    run("docker", "run", "--rm", "--user", "0", "-v", f"{WORK / 'ca'}:/certs",
        "--entrypoint", "keytool", "trinodb/trino:484", "-importcert", "-noprompt",
        "-alias", "test", "-file", "/certs/ca.crt", "-keystore", "/certs/truststore.jks",
        "-storepass", "changeit", "-storetype", "JKS")
    modulus = run("openssl", "rsa", "-in", str(key), "-noout", "-modulus").decode().strip().split("=")[1]
    jwks = json.dumps({"keys": [{"kty": "RSA", "kid": "fixture", "use": "sig", "alg": "RS256",
                                 "n": b64(bytes.fromhex(modulus)), "e": "AQAB"}]}).encode()

    class Keys(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(jwks)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 18443), Keys)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rendered = run("helm", "template", "trino", str(ROOT / "deploy/query"), "--namespace", "openings-query",
                   "--set", "bridgeImage=example.azurecr.io/openings-api@sha256:" + "a" * 64,
                   "--set", "aksIssuer=" + ISSUER, "--set", "secrets.clientId=test",
                   "--set", "secrets.tenantId=test", "--set", "secrets.vaultUrl=https://vault.invalid")
    config = next(item["data"] for item in yaml.safe_load_all(rendered) if item and item["kind"] == "ConfigMap")
    for name, content in config.items():
        folder = "access" if name == "rules.json" else "catalog" if name == "research.properties" else "config"
        (WORK / folder / name).write_text(content, encoding="utf-8")
    mounts = []
    for directory, destination in (("config", "/etc/trino"), ("catalog", "/etc/trino/catalog"),
                                    ("access", "/etc/trino/access"), ("tls", "/etc/trino/tls"),
                                    ("ca", "/etc/trino/ca")):
        mounts.extend(["-v", f"{WORK / directory}:{destination}:ro"])
    # The generated files are disposable fixtures, readable by the container UID.
    for path in WORK.rglob("*"):
        if path.is_file():
            path.chmod(0o644)

    def token(subject, audience="trino"):
        claims = {"iss": ISSUER, "sub": subject, "aud": audience, "exp": int(time.time()) + 600}
        unsigned = b64(json.dumps({"alg": "RS256", "kid": "fixture"}).encode()) + "." + b64(json.dumps(claims).encode())
        signature = run("openssl", "dgst", "-sha256", "-sign", str(key), input=unsigned.encode())
        return unsigned + "." + b64(signature)

    try:
        run("docker", "run", "-d", "--name", NAME, "--read-only", "--memory", "5g",
            "--tmpfs", "/tmp:rw,size=1g,uid=1000,gid=1000",
            "--tmpfs", "/data/trino:rw,size=1g,uid=1000,gid=1000",
            "--add-host", "host.docker.internal:host-gateway",
            "--add-host", "trino.openings-query.svc.cluster.local:127.0.0.1",
            "-p", "127.0.0.1:18444:8443", "-e", "TRINO_SHARED_SECRET",
            *mounts, "trinodb/trino:484", env={**os.environ, "TRINO_SHARED_SECRET": b64(os.urandom(48))})
        session = requests.Session()
        session.trust_env = False
        session.verify = str(cert)
        base = "https://localhost:18444"
        for _ in range(90):
            try:
                info = session.get(base + "/v1/info", timeout=2)
                if info.status_code == 200 and not info.json()["starting"]:
                    break
            except requests.RequestException:
                pass
            time.sleep(2)
        else:
            raise AssertionError("Trino did not become ready with the rendered production configuration")

        def query(subject, audience="trino", user="openings-api"):
            return session.post(base + "/v1/statement", data="SELECT 1",
                                headers={"Authorization": "Bearer " + token(subject, audience),
                                         "X-Trino-User": user}, timeout=10)

        good = "system:serviceaccount:openings-research:openings-api"

        def finish(response, user="openings-api"):
            page = response.json()
            rows = page.get("data", [])
            for _ in range(30):
                if "nextUri" not in page:
                    return page, rows
                from urllib.parse import urlsplit
                path = urlsplit(page["nextUri"]).path
                page = session.get(base + path, headers={"Authorization": "Bearer " + token(good),
                                                        "X-Trino-User": user}, timeout=10).json()
                rows.extend(page.get("data", []))
            raise AssertionError("Query did not finish")

        assert session.post(base + "/v1/statement", data="SELECT 1", timeout=10).status_code == 401
        assert query(good, audience="lakekeeper").status_code == 401
        assert query("system:serviceaccount:other:openings-api").status_code in (401, 403)
        impersonation = query(good, user="administrator")
        assert impersonation.status_code in (401, 403) or (
            impersonation.status_code == 200 and
            finish(impersonation, "administrator")[0].get("error", {}).get("errorName") == "PERMISSION_DENIED"
        ), impersonation.text
        response = query(good)
        assert response.status_code == 200, response.text
        page, rows = finish(response)
        assert "error" not in page, page.get("error")
        assert rows == [[1]], rows
        print("Rendered Trino TLS/JWT startup and negative-authentication checks passed")
    finally:
        logs = subprocess.run(["docker", "logs", NAME], capture_output=True, text=True)
        (WORK / "trino.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)
        server.shutdown()


if __name__ == "__main__":
    main()
