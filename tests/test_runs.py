"""Exercise the actual multipart and QPY payload without a live backend."""

import io
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from hashlib import sha256

import httpx
import pytest
from qiskit import QuantumCircuit, qpy

import bloch_trace.runs as runs_module
from bloch_trace import RunStatus, TraceClient

RUN_ID = "a173f85e-bd1e-4f2e-993f-62358e557811"


@pytest.fixture
def circuit() -> QuantumCircuit:
    result = QuantumCircuit(2)
    result.h(0)
    result.cx(0, 1)
    result.measure_all()
    return result


def _uploaded_file(request: httpx.Request) -> tuple[str, bytes]:
    headers = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
    message = BytesParser(policy=default).parsebytes(headers + request.read())
    assert isinstance(message, EmailMessage)
    parts = list(message.iter_parts())
    assert len(parts) == 1
    part = parts[0]
    assert part.get_param("name", header="Content-Disposition") == "file"
    assert part.get_content_type() == "application/octet-stream"
    filename = part.get_filename()
    payload = part.get_payload(decode=True)
    assert isinstance(filename, str)
    assert isinstance(payload, bytes)
    return filename, payload


def _accepted_body(request: httpx.Request) -> dict[str, object]:
    filename, payload = _uploaded_file(request)
    return {
        "id": RUN_ID,
        "filename": filename,
        "status": "QUEUED",
        "target": "trace_line_12_v1",
        "input_sha256": sha256(payload).hexdigest(),
    }


def _unexpected_request(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"Unexpected request to {request.url}")


@pytest.mark.parametrize("prefix", ["", "/proxy/"])
@pytest.mark.parametrize("api_key", [None, "test-key"])
def test_submission_round_trip(circuit: QuantumCircuit, prefix: str, api_key: str | None) -> None:
    requests: list[httpx.Request] = []
    original = circuit.copy()

    def accept(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202, json=_accepted_body(request))

    with TraceClient(
        base_url=f"https://example.test{prefix}",
        api_key=api_key,
        transport=httpx.MockTransport(accept),
    ) as trace:
        submission = trace.runs.submit(circuit, filename="bell.qpy")

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == f"{prefix.rstrip('/')}/api/trace/v1/runs"
    assert request.headers.get("Authorization") == (f"Bearer {api_key}" if api_key else None)
    filename, payload = _uploaded_file(request)
    assert filename == "bell.qpy"
    assert qpy.get_qpy_version(io.BytesIO(payload)) == 17
    assert qpy.load(io.BytesIO(payload)) == [original]
    assert circuit == original
    assert submission.id == RUN_ID
    assert submission.status is RunStatus.QUEUED
    assert submission.target == "trace_line_12_v1"
    assert submission.input_sha256 == sha256(payload).hexdigest()


def test_default_filename(circuit: QuantumCircuit) -> None:
    def accept(request: httpx.Request) -> httpx.Response:
        assert _uploaded_file(request)[0] == "circuit.qpy"
        return httpx.Response(202, json=_accepted_body(request))

    with TraceClient(
        base_url="https://example.test", transport=httpx.MockTransport(accept)
    ) as trace:
        trace.runs.submit(circuit)


@pytest.mark.parametrize(
    "filename", ["bad.txt", "../x.qpy", "a\\x.qpy", "a\n.qpy", "a" * 252 + ".qpy"]
)
def test_invalid_filename_never_sends(circuit: QuantumCircuit, filename: str) -> None:
    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(_unexpected_request)
        ) as trace,
        pytest.raises(ValueError, match="filename"),
    ):
        trace.runs.submit(circuit, filename=filename)


def test_wrong_input_never_sends() -> None:
    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(_unexpected_request)
        ) as trace,
        pytest.raises(TypeError, match="QuantumCircuit"),
    ):
        trace.runs.submit("not a circuit")


def test_size_limit_never_sends(circuit: QuantumCircuit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_module, "_MAX_QPY_BYTES", 1)
    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(_unexpected_request)
        ) as trace,
        pytest.raises(ValueError, match="10 MiB"),
    ):
        trace.runs.submit(circuit)


def test_unserializable_metadata_never_sends(circuit: QuantumCircuit) -> None:
    circuit.metadata = {"unsupported": object()}
    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(_unexpected_request)
        ) as trace,
        pytest.raises(TypeError),
    ):
        trace.runs.submit(circuit)


def test_closed_client_never_sends(circuit: QuantumCircuit) -> None:
    trace = TraceClient(
        base_url="https://example.test", transport=httpx.MockTransport(_unexpected_request)
    )
    trace.close()
    with pytest.raises(RuntimeError, match="closed"):
        trace.runs.submit(circuit)


@pytest.mark.parametrize("status", [307, 400, 401, 403, 413, 500, 503])
def test_http_errors_are_not_retried(circuit: QuantumCircuit, status: int) -> None:
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example.test/"})

    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(reject)
        ) as trace,
        pytest.raises(httpx.HTTPStatusError) as error,
    ):
        trace.runs.submit(circuit)

    assert error.value.response.status_code == status
    assert len(requests) == 1


def test_timeout_is_not_retried(circuit: QuantumCircuit) -> None:
    requests: list[httpx.Request] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Timed out", request=request)

    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(timeout)
        ) as trace,
        pytest.raises(httpx.ReadTimeout),
    ):
        trace.runs.submit(circuit)

    assert len(requests) == 1


@pytest.mark.parametrize("status", [200, 201, 204])
def test_requires_202(circuit: QuantumCircuit, status: int) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=_accepted_body(request))

    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(respond)
        ) as trace,
        pytest.raises(ValueError, match="Expected HTTP 202"),
    ):
        trace.runs.submit(circuit)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "invalid"),
        ("id", None),
        ("status", "UNKNOWN"),
        ("target", ""),
        ("input_sha256", "0" * 64),
    ],
)
def test_invalid_acknowledgement(circuit: QuantumCircuit, field: str, value: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = _accepted_body(request)
        body[field] = value
        return httpx.Response(202, json=body)

    with (
        TraceClient(
            base_url="https://example.test", transport=httpx.MockTransport(respond)
        ) as trace,
        pytest.raises(ValueError, match="Invalid Trace submission response"),
    ):
        trace.runs.submit(circuit)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null"])
def test_invalid_json_response(circuit: QuantumCircuit, body: bytes) -> None:
    with (
        TraceClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(202, content=body)),
        ) as trace,
        pytest.raises(ValueError, match="Invalid Trace submission response"),
    ):
        trace.runs.submit(circuit)
