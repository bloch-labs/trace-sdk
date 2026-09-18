"""Verify configuration reaches the HTTP transport without using a backend."""

import httpx
import pytest

from bloch_trace import TraceClient, __version__


class RecordingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.close_calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})

    def close(self) -> None:
        self.close_calls += 1


def test_defaults_make_no_request_and_do_not_read_an_api_key_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOCH_TRACE_API_KEY", "must-not-be-used")
    transport = RecordingTransport()
    client = TraceClient(base_url="http://localhost:8080", transport=transport)

    with client:
        assert client.base_url == "http://localhost:8080/"
        assert client.timeout == 30.0
        assert transport.requests == []

        # Exercise the configured transport; "probe" is not a Trace API endpoint.
        client._http.get("probe")

    request = transport.requests[0]
    assert "Authorization" not in request.headers
    assert request.headers["Accept"] == "application/json"
    assert request.headers["User-Agent"] == f"bloch-trace/{__version__}"
    assert request.extensions["timeout"] == dict.fromkeys(
        ["connect", "read", "write", "pool"], 30.0
    )
    assert client.is_closed
    assert transport.close_calls == 1


@pytest.mark.parametrize(
    "base_url", ["https://example.test/trace/v1", "https://example.test/trace/v1/"]
)
def test_custom_configuration_is_applied_to_requests(base_url: str) -> None:
    transport = RecordingTransport()
    with TraceClient(
        base_url=base_url,
        api_key="test-key",
        timeout=7.5,
        transport=transport,
    ) as client:
        assert client.timeout == 7.5
        assert "test-key" not in repr(client)
        client._http.get("probe")

    request = transport.requests[0]
    assert str(request.url) == "https://example.test/trace/v1/probe"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.extensions["timeout"] == dict.fromkeys(["connect", "read", "write", "pool"], 7.5)


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "localhost:8080",
        "/relative/path",
        "ftp://example.test",
        "https://",
        "http://example.test:invalid",
        "https://user:secret@example.test",
        "https://example.test?token=secret",
        "https://example.test#fragment",
        " https://example.test",
    ],
)
def test_rejects_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        TraceClient(base_url=base_url)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), -float("inf"), True])
def test_rejects_invalid_timeouts(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        TraceClient(base_url="https://example.test", timeout=timeout)


@pytest.mark.parametrize(
    "api_key", ["", " ", " leading", "trailing ", "bad\r\nheader", "non-ascii-é"]
)
def test_rejects_invalid_api_keys_without_echoing_them(api_key: str) -> None:
    with pytest.raises(ValueError, match="api_key") as error:
        TraceClient(base_url="https://example.test", api_key=api_key)

    if api_key.strip():
        assert api_key not in str(error.value)


def test_close_is_idempotent_and_closed_clients_cannot_be_reopened() -> None:
    transport = RecordingTransport()
    client = TraceClient(base_url="https://example.test", transport=transport)

    client.close()
    client.close()

    assert client.is_closed
    assert transport.close_calls == 1
    with pytest.raises(RuntimeError), client:
        pass


def test_context_manager_closes_on_error_without_suppressing_it() -> None:
    transport = RecordingTransport()
    client = TraceClient(base_url="https://example.test", transport=transport)

    with pytest.raises(RuntimeError, match="application failed"), client:
        raise RuntimeError("application failed")

    assert client.is_closed
    assert transport.close_calls == 1


def test_redirects_are_not_followed() -> None:
    requests: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example.test/"})

    with TraceClient(
        base_url="https://example.test",
        api_key="test-key",
        transport=httpx.MockTransport(redirect),
    ) as client:
        response = client._http.get("probe")

    assert response.status_code == 307
    assert len(requests) == 1
