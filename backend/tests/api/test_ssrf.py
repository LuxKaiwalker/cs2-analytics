"""URL import guards.

The threat model is an operator pasting a hostile link, so the table below is the set of
URLs that would make the server reach something only the server can reach.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.ingest import fetch


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://127.0.0.1/a.dem", "plain http is off by default"),
        ("https://127.0.0.1/a.dem", "loopback"),
        ("https://localhost/a.dem", "loopback by name"),
        ("https://[::1]/a.dem", "IPv6 loopback"),
        ("https://169.254.169.254/latest/meta-data/", "cloud metadata endpoint"),
        ("https://10.0.0.1/a.dem", "private class A"),
        ("https://192.168.1.1/a.dem", "private class C"),
        ("https://172.16.0.1/a.dem", "private class B"),
        ("https://100.64.0.1/a.dem", "carrier-grade NAT"),
        ("https://0.0.0.0/a.dem", "unspecified address"),
        ("https://[::ffff:127.0.0.1]/a.dem", "IPv4-mapped loopback in disguise"),
        ("https://[64:ff9b::7f00:1]/a.dem", "NAT64-embedded loopback"),
        ("https://user:pass@example.com/a.dem", "embedded credentials"),
        ("https://example.com:8080/a.dem", "non-standard port"),
        ("file:///etc/passwd", "non-http scheme"),
        ("ftp://example.com/a.dem", "non-http scheme"),
        ("gopher://example.com/a.dem", "non-http scheme"),
    ],
)
def test_hostile_urls_are_refused(url: str, reason: str, settings: Settings) -> None:
    with pytest.raises(fetch.ImportRejectedError) as caught:
        fetch._build_target(url, settings)
    assert caught.value.code in {
        "url_not_allowed",
        "url_scheme_not_allowed",
        "url_port_not_allowed",
        "url_invalid",
    }, f"{url} ({reason}) produced {caught.value.code}"


def test_an_overlong_url_is_refused(settings: Settings) -> None:
    with pytest.raises(fetch.ImportRejectedError):
        fetch.validate_url("https://example.com/" + "a" * 4000, settings)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("10.0.0.5", False),
        ("172.31.255.255", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("::ffff:10.0.0.1", False),
        ("64:ff9b::a00:1", False),
        ("224.0.0.1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_address_classification(address: str, expected: bool) -> None:
    assert fetch.is_global_address(address) is expected


def test_resolution_fails_closed_when_any_address_is_private(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host with one public and one private record must be refused outright.

    Accepting it because the first record looked fine is exactly the bug the fail-closed
    rule exists to prevent.
    """
    import socket

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(fetch.ImportRejectedError) as caught:
        fetch.resolve_and_check("mixed.example.com", 443, settings)
    assert caught.value.code == "url_not_allowed"


def test_a_fully_public_host_is_accepted(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert fetch.resolve_and_check("example.com", 443, settings) == "93.184.216.34"


def test_unresolvable_hosts_report_a_failure_not_an_acceptance(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def fake_getaddrinfo(*_args: object, **_kwargs: object) -> list:
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(fetch.ImportFailedError):
        fetch.resolve_and_check("nothing.invalid", 443, settings)


def test_http_is_allowed_only_when_explicitly_enabled(settings: Settings) -> None:
    with pytest.raises(fetch.ImportRejectedError):
        fetch.validate_url("http://example.com/a.dem", settings)
    permissive = settings.model_copy(update={"allow_http_import": True})
    url, host, port = fetch.validate_url("http://example.com/a.dem", permissive)
    assert host == "example.com"
    assert port == 80
    assert url.startswith("http://")


def test_the_proxy_environment_cannot_redirect_the_request(settings: Settings) -> None:
    """``trust_env=False`` is what stops HTTP_PROXY bypassing every address check.

    Asserted on the client construction rather than the behaviour, because a proxy that
    actually honoured the variable would silently defeat the whole module.
    """
    import inspect

    source = inspect.getsource(fetch.fetch_demo)
    assert "trust_env=False" in source
    assert "follow_redirects=False" in source


def test_import_can_be_disabled_entirely(settings: Settings) -> None:
    disabled = settings.model_copy(update={"allow_url_import": False})
    with pytest.raises(fetch.ImportRejectedError) as caught:
        fetch.fetch_demo("https://example.com/a.dem", disabled, "x" * 32)
    assert caught.value.code == "url_import_disabled"


def test_the_import_endpoint_rejects_a_private_url(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.post("/api/matches/import", json={"url": "https://127.0.0.1/a.dem"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "url_not_allowed"


def test_the_import_endpoint_rejects_a_malformed_url(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    response = client.post("/api/matches/import", json={"url": "not a url"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"validation_error", "url_invalid"}


def test_error_messages_do_not_echo_the_remote_response(settings: Settings) -> None:
    """The endpoint must not become a readable proxy for arbitrary hosts."""
    import inspect

    source = inspect.getsource(fetch.fetch_demo)
    assert "response.text" not in source
    assert "response.content" not in source
