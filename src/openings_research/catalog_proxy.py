"""Loopback-only Trino REST bridge that re-reads a projected catalog token per request."""

import os
import ssl
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from fastapi import FastAPI
from fastapi import Request as IncomingRequest
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

MAX_REQUEST = 2 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CatalogBridge:
    def __init__(self, upstream, token_file, opener):
        parsed = urlsplit(upstream)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("Catalog upstream must be an HTTPS origin without credentials")
        self.upstream = upstream.rstrip("/")
        self.token_file = Path(token_file)
        self.opener = opener

    def forward(self, method, path, headers, body):
        if method not in {"GET", "HEAD", "POST"} or not path.startswith("/catalog/"):
            return 403, b"Catalog route denied", "text/plain"
        if "\\" in path or any(part in ("..", ".") for part in path.split("/")) or "%2e" in path.lower():
            return 403, b"Catalog route denied", "text/plain"
        if len(body) > MAX_REQUEST:
            return 413, b"Request too large", "text/plain"
        token = self.token_file.read_text().strip()
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Invalid projected token")
        outgoing = {key: value for key, value in headers.items()
                    if key.lower() in {"accept", "content-type", "x-iceberg-access-delegation"}}
        outgoing["Authorization"] = "Bearer " + token
        request = Request(self.upstream + path, data=body if method == "POST" else None,
                          headers=outgoing, method=method)
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            if 300 <= response.status < 400:
                return 502, b"Catalog redirects are not permitted", "text/plain"
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                return 502, b"Catalog response too large", "text/plain"
            return response.status, payload, response.headers.get("Content-Type", "application/json")


def create_app(bridge):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy(request: IncomingRequest, path: str):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST:
                return Response("Request too large", status_code=413)
        target = "/" + path
        if request.url.query:
            target += "?" + request.url.query
        try:
            status, payload, content_type = await run_in_threadpool(
                bridge.forward, request.method, target, dict(request.headers), bytes(body)
            )
        except Exception:
            # Do not emit credentials, upstream URLs, provider errors or request bodies.
            return Response("Catalog unavailable", status_code=502)
        return Response(payload, status_code=status, headers={"Content-Type": content_type})

    return app


def main():
    import uvicorn

    context = ssl.create_default_context(cafile=os.environ["CATALOG_CA_FILE"])
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())
    bridge = CatalogBridge(os.environ["CATALOG_ORIGIN"], os.environ["CATALOG_TOKEN_FILE"], opener)
    uvicorn.run(create_app(bridge), host="127.0.0.1", port=8182, access_log=False)


if __name__ == "__main__":
    main()
