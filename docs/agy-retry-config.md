# AGY Retry Configuration

> **Status: not implemented.** The configuration variables below describe a proposed design.
> Nothing in this repository reads them yet; `scripts/retry_wrapper.py` does not consume them (#30).

## Purpose

This document describes a lightweight configuration approach for the **AGY client** to automatically handle transient model-service errors (e.g., empty responses, HTTP 503/429) by invoking the retry wrapper defined in `scripts/retry_wrapper.py`.

## Configuration Options

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `AGY_RETRY_ENABLED` | `true` | Globally enable or disable the retry logic. When `false` the client calls the model directly.
| `AGY_RETRY_MAX` | `3` | Maximum number of retry attempts before giving up.
| `AGY_RETRY_BACKOFF` | `1` | Base back-off delay in seconds. Actual delay = `base * 2**(attempt-1)`.
| `AGY_RETRY_LOG_LEVEL` | `warning` | Logging level for retry attempts (`debug`, `info`, `warning`, `error`).

## Usage Example (Python)
```python
import os
from retry_wrapper import retry_on_transient_error
from agy_client import AGYClient  # hypothetical import

# Load configuration from environment
enabled = os.getenv('AGY_RETRY_ENABLED', 'true').lower() == 'true'
max_retries = int(os.getenv('AGY_RETRY_MAX', '3'))
backoff = float(os.getenv('AGY_RETRY_BACKOFF', '1'))

client = AGYClient()

# Wrap the low-level request method if retries are enabled
if enabled:
    client.send_request = retry_on_transient_error(
        client.send_request,
        max_retries=max_retries,
        base_delay=backoff,
    )

# Normal usage remains unchanged
response = client.send_request(prompt='Hello world')
print(response)
```

## Integration Steps
1. **Add the wrapper script** (`scripts/retry_wrapper.py`) to the project – already provided.
2. **Update the client entry point** (e.g., `green-roomz/green_agent/main.py` or wherever the model request is made) to import the wrapper and apply it conditionally based on the env vars.
3. **Document the env vars** in the project README so operators know how to adjust retry behaviour.
4. **Optional**: expose a CLI flag `--no-retry` that sets `AGY_RETRY_ENABLED=false` for debugging.

## Benefits
* **Resilience** – transient server-load spikes no longer abort workflows.
* **Observability** – configurable logging allows operators to monitor retry activity.
* **Low overhead** – exponential back-off caps total wait time; defaults are safe for most use-cases.

---
*This file is intended for version control and should be committed alongside the other documentation changes.*
