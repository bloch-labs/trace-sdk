import os

from bloch_trace import TraceClient

# Setup a client without an API key
with TraceClient(
    base_url="https://localhost:8080",
    # `api_key=None` omits the Authorization header
    # A supplied key is sent as `Authorization: Bearer <key>`;
    api_key=None,
    timeout=30.0,
) as trace:
    print(trace.base_url)
    print(trace.timeout)

# Setup a client with an API key
with TraceClient(
    base_url="http://localhost:8080",
    api_key=os.environ.get("BLOCH_TRACE_API_KEY"),
) as trace:
    print(trace.base_url)
