# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def search_registry(query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    query = query.strip()[:80]
    cached = _cache.get(query)
    if cached and time.monotonic() - cached[0] < 600:
        return cached[1]
    params = {"limit": str(max(1, min(limit, 30))), "version": "latest"}
    if query:
        params["search"] = query
    request = Request(
        f"{REGISTRY_URL}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": "GUADE-Local-Workflow/0.1"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(4_000_000).decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load the MCP registry: {exc}") from exc

    servers = []
    for entry in payload.get("servers", []):
        server = entry.get("server", {})
        official = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        if official.get("status") not in {None, "active"}:
            continue
        connection = _connection(server)
        if not connection:
            continue
        description = re.sub(r"\s+", " ", str(server.get("description", ""))).strip()
        servers.append({
            "name": server.get("name", ""),
            "title": server.get("title") or server.get("name", "MCP server"),
            "description": description[:500],
            "version": server.get("version", ""),
            "repository": _safe_https((server.get("repository") or {}).get("url", "")),
            "website": server.get("websiteUrl", ""),
            "connection": connection,
            "category": _category(f"{server.get('name', '')} {server.get('title', '')} {description}"),
        })
    _cache[query] = (time.monotonic(), servers)
    return servers


def _connection(server: dict[str, Any]) -> dict[str, Any] | None:
    for remote in server.get("remotes", []):
        if remote.get("type") not in {"streamable-http", "http"} or not isinstance(remote.get("url"), str):
            continue
        headers = []
        for header in remote.get("headers", []):
            name = header.get("name")
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9-]{1,80}", name):
                env_name = "GUADE_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
                headers.append({"name": name, "env_name": env_name, "required": bool(header.get("isRequired")), "description": str(header.get("description", ""))[:200]})
        url = _safe_https(remote["url"])
        if url:
            return {"transport": "http", "url": url, "headers": headers}

    for package in server.get("packages", []):
        registry = package.get("registryType")
        identifier = package.get("identifier")
        version = package.get("version") or server.get("version")
        if not isinstance(identifier, str) or not version:
            continue
        if registry == "npm":
            if not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", identifier, re.I) or not re.fullmatch(r"[A-Za-z0-9.+_-]{1,100}", str(version)):
                continue
            return {"transport": "stdio", "command": ["npx"], "args": ["-y", f"{identifier}@{version}"], "package": f"npm:{identifier}@{version}"}
        if registry == "pypi":
            if not re.fullmatch(r"[A-Za-z0-9._-]+", identifier) or not re.fullmatch(r"[A-Za-z0-9.+_-]{1,100}", str(version)):
                continue
            return {"transport": "stdio", "command": ["uvx"], "args": [f"{identifier}=={version}"], "package": f"pypi:{identifier}=={version}"}
    return None


def _safe_https(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return value


def _category(value: str) -> str:
    text = value.lower()
    if any(word in text for word in ("crypto", "wallet", "blockchain", "web3")):
        return "crypto"
    if "bank" in text:
        return "banking"
    if any(word in text for word in ("finance", "payment", "stripe", "paypal")):
        return "payments"
    if any(word in text for word in ("ein", "duns", "business identity", "tax id")):
        return "business_identity"
    return "general"
