"""Conservative identity and submission invariants."""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class Job:
    title: str
    company: str
    url: str
    ats_provider: str | None = None
    ats_id: str | None = None


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Job URL must be an absolute HTTP(S) URL")
    if parts.username or parts.password:
        raise ValueError("Credentials in job URLs are not allowed")
    host = parts.hostname.lower()
    if parts.port and not ((parts.scheme.lower(), parts.port) in (("http", 80), ("https", 443))):
        host += f":{parts.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not k.lower().startswith("utm_") and k.lower() != "gclid"))
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/") or "/", query, ""))
