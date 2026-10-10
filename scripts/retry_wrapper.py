"""Retry wrapper for AGY client model calls.

This module provides a single function `retry_on_transient_error` that can be used to
wrap any callable that performs a model request (e.g., a function that sends a HTTP
POST to the AGY endpoint). The wrapper catches transient errors such as empty
responses, HTTP 503 Service Unavailable, or HTTP 429 Too Many Requests and retries
with exponential back-off.

Example usage::

    from retry_wrapper import retry_on_transient_error

    def call_model(payload):
        # perform the actual request, raise an exception on failure
        ...

    safe_call = retry_on_transient_error(call_model, max_retries=3, base_delay=1)
    result = safe_call(payload)

Parameters
==========
* ``func`` – The function performing the model request.
* ``max_retries`` – Maximum number of retry attempts (default 3).
* ``base_delay`` – Base delay in seconds for exponential back-off (default 1).

The wrapper returns a new callable that incorporates the retry logic.
"""
import time
import functools
import logging
from typing import Callable, Any, Tuple

logger = logging.getLogger(__name__)


def _is_transient_error(exc: Exception) -> bool:
    """Return True if *exc* looks like a transient model-service error.

    Currently treats the following as transient:
    * HTTPError with status 503 or 429
    * ValueError/RuntimeError indicating an empty model output
    """
    # Very basic heuristics – callers can subclass or wrap their own exceptions.
    msg = str(exc).lower()
    if "503" in msg or "service unavailable" in msg:
        return True
    if "429" in msg or "too many requests" in msg:
        return True
    if "empty response" in msg or "no output" in msg:
        return True
    return False


def retry_on_transient_error(
    func: Callable[..., Any],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Callable[..., Any]:
    """Wrap *func* with retry-on-transient-error logic.

    The returned callable forwards all positional and keyword arguments to *func*.
    If a transient error is raised, the call is retried after ``base_delay`` seconds,
    multiplied by 2**attempt (exponential back-off). After ``max_retries`` attempts the
    original exception is re-raised.
    """

    @functools.wraps(func)
    def wrapper(*args: Tuple[Any], **kwargs: Any):
        attempt = 0
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                if not _is_transient_error(exc) or attempt >= max_retries:
                    logger.error("Non-transient or max-retry error on attempt %s: %s", attempt + 1, exc)
                    raise
                attempt += 1
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Transient error on attempt %s: %s – retrying after %.1f s", attempt, exc, delay
                )
                time.sleep(delay)

    return wrapper

# Simple self-test when run as a script
if __name__ == "__main__":
    import random

    def flaky(payload):
        # Simulate a flaky model call that fails half the time
        if random.random() < 0.5:
            raise RuntimeError("Empty response from model")
        return {"result": "ok", "payload": payload}

    safe_flaky = retry_on_transient_error(flaky, max_retries=4, base_delay=0.5)
    print(safe_flaky({"msg": "test"}))
