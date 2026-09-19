"""Client configuration and HTTP connection lifecycle."""

import math
from importlib.metadata import version
from types import TracebackType
from typing import Self

import httpx

from bloch_trace.runs import Runs


def _validate_base_url(value: str) -> httpx.URL:
    if any(character.isspace() for character in value):
        raise ValueError("base_url must not contain whitespace")

    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError("base_url must be a valid absolute HTTP or HTTPS URL") from None

    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
    if url.userinfo:
        raise ValueError("base_url must not contain credentials; use api_key instead")
    if "?" in value or "#" in value:
        raise ValueError("base_url must not contain a query string or fragment")

    path = url.raw_path
    return url.copy_with(raw_path=path if path.endswith(b"/") else path + b"/")


class TraceClient:
    """Synchronous Bloch Trace client.

    Construction configures the client without contacting the backend.
    ``api_key=None`` omits authentication; no environment variables are read
    for SDK credentials. The backend decides whether authentication is required.

    ``timeout`` is a positive, finite number of seconds applied to HTTPX's
    connect, read, write and pool timeouts, not a total run deadline.

    Use as a context manager or call ``close()`` when finished. This client
    owns its HTTP connection pool, including any supplied transport.
    """

    def __init__(
        self,
        *,
        # TODO:
        # Default to the hosted API after deployment; retain an explicit override
        # for local development, staging and testing.
        base_url: str,
        # TODO:
        # Require a key for hosted usage once backend authentication exists.
        # Unauthenticated development must remain an explicit, separate mode.
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = _validate_base_url(base_url)

        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive, finite number of seconds")

        headers = {
            "Accept": "application/json",
            "User-Agent": f"bloch-trace/{version('bloch-trace')}",
        }
        if api_key is not None:
            if not api_key or any(not 33 <= ord(character) <= 126 for character in api_key):
                raise ValueError("api_key must be non-empty printable ASCII without whitespace")
            headers["Authorization"] = f"Bearer {api_key}"

        self._timeout = float(timeout)
        self._http = httpx.Client(
            base_url=url,
            headers=headers,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=False,
            transport=transport,
        )
        self._runs = Runs(self._http)

    @property
    def runs(self) -> Runs:
        """Return the run operations associated with this client."""
        return self._runs

    @property
    def base_url(self) -> str:
        """Return the normalised API base URL, including its trailing slash."""
        return str(self._http.base_url)

    @property
    def timeout(self) -> float:
        """Return the configured HTTP timeout in seconds."""
        return self._timeout

    @property
    def is_closed(self) -> bool:
        """Return whether the client's HTTP connection pool has been closed."""
        return self._http.is_closed

    def close(self) -> None:
        """Close the connection pool. Calling this more than once is safe."""
        self._http.close()

    def __enter__(self) -> Self:
        self._http.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._http.__exit__(exc_type, exc_value, traceback)

    def __repr__(self) -> str:
        return f"TraceClient(base_url={self.base_url!r}, timeout={self.timeout!r})"
