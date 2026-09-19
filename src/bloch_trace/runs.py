"""Circuit submission using the Trace v1 multipart API."""

import io
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

import httpx
from qiskit import QuantumCircuit, qpy

_MAX_QPY_BYTES = 10 * 1024 * 1024
_QPY_VERSION = 17


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    BASELINING = "BASELINING"
    OPTIMISING = "OPTIMISING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RunSubmission:
    """Submission acknowledgement, not a completed result or live run handle."""

    id: str
    status: RunStatus
    target: str
    input_sha256: str


def _validate_filename(filename: str) -> None:
    if (
        not filename.lower().endswith(".qpy")
        or len(filename.encode("utf-16-le")) > 510
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in filename)
    ):
        raise ValueError("filename must be a .qpy basename of at most 255 UTF-16 code units")


def _parse_submission(response: httpx.Response, expected_sha256: str) -> RunSubmission:
    try:
        body: object = response.json()
        if not isinstance(body, dict):
            raise ValueError

        run_id = body.get("id")
        status = body.get("status")
        target = body.get("target")
        input_sha256 = body.get("input_sha256")

        if (
            not isinstance(run_id, str)
            or not isinstance(status, str)
            or not isinstance(target, str)
            or not target
            or input_sha256 != expected_sha256
        ):
            raise ValueError

        return RunSubmission(
            id=str(UUID(run_id)),
            status=RunStatus(status),
            target=target,
            input_sha256=expected_sha256,
        )
    except ValueError:
        raise ValueError(
            "Invalid Trace submission response. A run may already exist; do not blindly retry."
        ) from None


class Runs:
    """Run operations sharing their parent TraceClient's HTTP connection pool."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def submit(
        self,
        circuit: QuantumCircuit,
        *,
        filename: str = "circuit.qpy",
    ) -> RunSubmission:
        """Serialize one circuit and create one persisted run.

        This does not transpile, bind parameters, wait or retry. Semantic circuit
        validation happens asynchronously in the backend after acceptance.
        """
        if self._http.is_closed:
            raise RuntimeError("Cannot submit using a closed TraceClient")
        if not isinstance(circuit, QuantumCircuit):
            raise TypeError("circuit must be a single Qiskit QuantumCircuit")
        _validate_filename(filename)

        with io.BytesIO() as buffer:
            qpy.dump(circuit, buffer, version=_QPY_VERSION)
            payload = buffer.getvalue()

        if len(payload) > _MAX_QPY_BYTES:
            raise ValueError("Serialized circuit exceeds the backend's 10 MiB QPY limit")

        response = self._http.post(
            "api/trace/v1/runs",
            files={"file": (filename, payload, "application/octet-stream")},
        )
        response.raise_for_status()
        if response.status_code != 202:
            raise ValueError(
                "Expected HTTP 202 from Trace. A run may already exist; do not blindly retry."
            )

        return _parse_submission(response, sha256(payload).hexdigest())
