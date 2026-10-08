# Known Issues

- **Model:** GPT-OSS-120B-MEDIUM (transient errors)
  - **Symptom:** Occasionally the model fails with an internal error or timeout during inference, often returning an empty response or HTTP 503.
  - **Temporary Workaround:** Pend a retry of the request. The system will automatically retry the operation after a short back‑off. This covers transient server‑load conditions.
