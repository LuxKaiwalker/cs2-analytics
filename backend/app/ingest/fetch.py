"""Import a demo from a public URL, guarded against SSRF.

**Threat model, stated plainly.** This app binds to localhost and has no authentication,
so the realistic risk is not a remote attacker but the operator pasting a hostile link —
one crafted to make the server fetch something only the server can reach: a metadata
endpoint, a service on the loopback interface, a box on the LAN. The guards below are
proportionate to that, and the residual gaps are documented rather than papered over.

Layers, each closing something the previous one cannot:

1. **Scheme, port and host shape.** https only unless http is explicitly enabled; no
   embedded credentials; only ports 80 and 443; the host is IDNA-encoded so a Unicode
   homograph cannot smuggle a different name past validation.
2. **Address validation, fail-closed.** Every address the host resolves to must be
   globally routable. If *any* resolved address is private the request is refused —
   checking only the first would let a host with one public and one private record
   through. IPv4-mapped IPv6 is unwrapped first, since ``::ffff:127.0.0.1`` is loopback
   wearing a disguise.
3. **No implicit redirects.** Redirects are followed manually, at most five, and every
   hop is re-validated. A hop may legitimately point somewhere public and still be a
   redirect *into* the private range — which is exactly how a naive fetcher is
   exploited. https→http downgrades are refused.
4. **Address pinning.** The connection is made to the validated IP with the original
   hostname preserved for TLS, so a DNS record that changes between validation and
   connection cannot redirect us. This is the one guard that actually closes DNS
   rebinding; if the transport cannot support it, the code degrades to validate-then-
   connect and records that the narrow race remains.
5. **Budgets.** Connect, read and overall deadlines, plus the same streaming size cap as
   a direct upload, applied to the bytes actually received.

**Not solved, deliberately:** a public host the operator chooses to fetch is fetched, so
error messages never echo response bodies or headers — the endpoint must not become a
readable proxy. Internal services on globally-routable addresses are indistinguishable
from the internet and are not blocked. Neither is fixable without an egress allowlist,
which is disproportionate for a single-user local tool.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx

from app.config import Settings
from app.ingest.storage import StoredDemo, store_iter

logger = logging.getLogger(__name__)

_ALLOWED_PORTS = {80, 443}
_MAX_URL_LENGTH = 2048
_CHUNK = 1 << 18
#: NAT64 well-known prefix: 64:ff9b::/96 embeds IPv4, including private ranges.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class ImportRejectedError(Exception):
    """The URL is not one we are willing to fetch."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message


class ImportFailedError(Exception):
    """The fetch itself failed (DNS, connection, timeout, bad status)."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _Target:
    url: str
    host: str
    port: int
    scheme: str
    address: str
    """The validated IP the request will actually be sent to."""


def _reject(code: str, message: str) -> ImportRejectedError:
    return ImportRejectedError(code, message)


def is_global_address(raw: str) -> bool:
    """Whether an address is a routable public unicast address we will fetch from.

    ``is_global`` covers loopback, link-local (so cloud metadata at 169.254.169.254),
    private ranges, CGNAT and reserved space — but **not** multicast: Python reports
    ``224.0.0.1`` and ``ff00::1`` as global. The non-unicast families are therefore
    excluded explicitly rather than relying on that one flag.

    Two further cases are private addresses in disguise and are unwrapped first:
    IPv4-mapped IPv6 (``::ffff:127.0.0.1`` is loopback) and the NAT64 well-known prefix
    (``64:ff9b::/96`` embeds an arbitrary IPv4 address, private ones included).
    """
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address in _NAT64:
            return False
    if (
        address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
    ):
        return False
    return bool(address.is_global)


def validate_url(raw: str, settings: Settings) -> tuple[str, str, int]:
    """Check the URL's shape. Returns ``(normalized_url, host, port)``."""
    if not raw or len(raw) > _MAX_URL_LENGTH:
        raise _reject("url_invalid", "The URL is missing or too long.")
    try:
        parsed = urlparse(raw.strip())
    except ValueError as exc:
        raise _reject("url_invalid", "The URL could not be parsed.") from exc

    allowed_schemes = {"https"} | ({"http"} if settings.allow_http_import else set())
    if parsed.scheme not in allowed_schemes:
        raise _reject(
            "url_scheme_not_allowed",
            "Only https:// URLs can be imported."
            if not settings.allow_http_import
            else "Only http:// and https:// URLs can be imported.",
        )
    if parsed.username or parsed.password:
        raise _reject("url_invalid", "URLs containing credentials are not accepted.")
    if not parsed.hostname:
        raise _reject("url_invalid", "The URL has no host.")

    try:
        # IDNA-encode so a Unicode homograph cannot resolve to a different host than the
        # one that was validated.
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise _reject("url_invalid", "The URL host is not a valid domain name.") from exc

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise _reject(
            "url_port_not_allowed",
            "Only the standard web ports 80 and 443 can be imported from.",
        )
    normalized = urlunparse(parsed._replace(netloc=_netloc(host, parsed.port)))
    return normalized, host, port


def _netloc(host: str, explicit_port: int | None) -> str:
    bracketed = f"[{host}]" if ":" in host else host
    return f"{bracketed}:{explicit_port}" if explicit_port else bracketed


def resolve_and_check(host: str, port: int, settings: Settings) -> str:
    """Resolve ``host`` and require **every** address to be globally routable.

    Fail-closed on purpose: a host that returns one public and one private address is
    refused outright. Accepting it because the first record looked fine is precisely the
    bug this function exists to prevent.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImportFailedError("The URL's host could not be resolved.", detail=str(exc)) from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise ImportFailedError("The URL's host returned no addresses.")
    if settings.allow_private_import:
        logger.warning("private-address imports are enabled; SSRF protection is disabled")
        return addresses[0]
    blocked = [a for a in addresses if not is_global_address(a)]
    if blocked:
        raise _reject(
            "url_not_allowed",
            "That URL resolves to a private or internal address and cannot be imported.",
        )
    return addresses[0]


def _build_target(raw: str, settings: Settings) -> _Target:
    url, host, port = validate_url(raw, settings)
    address = resolve_and_check(host, port, settings)
    parsed = urlparse(url)
    return _Target(url=url, host=host, port=port, scheme=parsed.scheme, address=address)


def _pinned_request(client: httpx.Client, target: _Target) -> httpx.Response:
    """Issue the request against the validated IP, keeping the hostname for TLS.

    Pinning is what closes DNS rebinding: without it the name is resolved a second time
    when connecting, and that second answer is unvalidated. ``sni_hostname`` keeps
    certificate verification pointed at the real hostname, so pinning does not weaken TLS.
    If the transport rejects the extension we fall back to connecting by hostname and log
    that the narrow re-resolution race is live.
    """
    parsed = urlparse(target.url)
    pinned = urlunparse(parsed._replace(netloc=_netloc(target.address, parsed.port)))
    headers = {"Host": _netloc(target.host, parsed.port), "Accept": "*/*"}
    try:
        return client.send(
            client.build_request(
                "GET", pinned, headers=headers, extensions={"sni_hostname": target.host}
            ),
            stream=True,
        )
    except (httpx.UnsupportedProtocol, httpx.InvalidURL, TypeError) as exc:
        logger.warning(
            "address pinning unavailable (%s); connecting by hostname, so a DNS change "
            "between validation and connection is not covered",
            exc,
        )
        return client.send(client.build_request("GET", target.url), stream=True)


def fetch_demo(url: str, settings: Settings, match_id: str) -> StoredDemo:
    """Download ``url`` into validated storage, or raise.

    Raises:
        ImportRejectedError: the URL is not one we will fetch.
        ImportFailedError: the transfer failed.
        storage.UploadTooLargeError: the response exceeded the size cap.
    """
    if not settings.allow_url_import:
        raise _reject("url_import_disabled", "Importing from a URL is disabled.")

    deadline = time.monotonic() + settings.import_total_deadline_s
    timeout = httpx.Timeout(
        connect=settings.import_connect_timeout_s,
        read=settings.import_read_timeout_s,
        write=settings.import_connect_timeout_s,
        pool=settings.import_connect_timeout_s,
    )
    with httpx.Client(
        follow_redirects=False,
        # Without this, HTTP_PROXY in the environment would route the request through a
        # proxy and bypass every address check above.
        trust_env=False,
        timeout=timeout,
        max_redirects=0,
    ) as client:
        target = _build_target(url, settings)
        for _hop in range(settings.import_max_redirects + 1):
            response = _pinned_request(client, target)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ImportFailedError("The server sent a redirect with no target.")
                    next_url = str(httpx.URL(target.url).join(location))
                    next_target = _build_target(next_url, settings)
                    if target.scheme == "https" and next_target.scheme == "http":
                        raise _reject(
                            "url_not_allowed",
                            "The URL redirects from https to http, which is not followed.",
                        )
                    target = next_target
                    continue
                if response.status_code != httpx.codes.OK:
                    # Deliberately does not echo the body: this endpoint must not become
                    # a readable proxy for whatever the operator points it at.
                    raise ImportFailedError(
                        f"The server responded with HTTP {response.status_code}."
                    )
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > settings.max_demo_bytes:
                    from app.ingest.storage import UploadTooLargeError  # noqa: PLC0415

                    raise UploadTooLargeError(int(declared), settings.max_demo_bytes)
                return store_iter(
                    settings,
                    match_id,
                    _stream(response, deadline),
                    display_name=_name_from_url(target.url),
                )
            finally:
                response.close()
        raise ImportFailedError("The URL redirected too many times.")


def _stream(response: httpx.Response, deadline: float) -> Iterator[bytes]:
    for chunk in response.iter_bytes(_CHUNK):
        if time.monotonic() > deadline:
            raise ImportFailedError("The download took too long and was stopped.")
        yield chunk


def _name_from_url(url: str) -> str:
    tail = urlparse(url).path.rsplit("/", 1)[-1]
    return tail or "imported.dem"
