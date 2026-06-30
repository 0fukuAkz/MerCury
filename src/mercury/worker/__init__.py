"""Campaign worker tier (arq-based).

Decouples campaign *execution* from the web process so the web tier can scale
horizontally. Opt-in via ``CAMPAIGN_EXECUTION_MODE=worker``; default
(``inprocess``) preserves the existing in-thread behavior exactly.

- ``queue``: the enqueue side, imported by the web process (arq imported lazily
  so the default path needs no arq).
- ``tasks``: the worker side — ``arq mercury.worker.tasks.WorkerSettings``.
"""
