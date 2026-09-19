"""Submit a Bell circuit to an explicitly configured local development backend."""

import os

from qiskit import QuantumCircuit

from bloch_trace import TraceClient

circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()

with TraceClient(
    base_url="http://localhost:8000",
    api_key=os.environ.get("BLOCH_TRACE_API_KEY"),
) as trace:
    submission = trace.runs.submit(circuit, filename="bell.qpy")

print(f"Run ID: {submission.id}")
print(f"Status at submission: {submission.status}")
print(f"Target: {submission.target}")
print(f"Input SHA-256: {submission.input_sha256}")
