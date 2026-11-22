"""The gate (Phase 4 spec §12.6, P15, P23, P38): its own OS process (`server`), a hash-chained
decision log (`log`), single-use HMAC allow tokens (`tokens`) and the environment's client
(`client`). The decision itself is `adr_store.bindings.decide`. Nothing here imports z3."""
