"""The `gate` fixture (Task 18, preflight C2, N10): a gate process (`python -m
adr_store.gate.server`, started by `client.GateProcess` with the key on an inherited pipe)
over `make_units_built_with_bindings`, its socket in a short private directory under /tmp,
its log under `tmp_path`, a short I/O deadline, and the store's ACL synced again at the real
clock (the fixture syncs at the fixed `T0`, which the gate's freshness check would find stale
and so withhold every rule text). No network; every process is reaped and every pipe
closed."""

from __future__ import annotations

import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from adr_store import acl
from adr_store.bindings.manifest import read_bindings_head
from adr_store.gate.client import GateClient, GateProcess, private_socket
from adr_store.store import Store
from adr_store.units.overlay import read_units_head
from tests.store.units_fixtures import make_units_built_with_bindings

AS_OF = "2026-08-14T05:30:00"          # a Friday under the newest 33 CFR 117 version
DEADLINE = 3.0


def fresh_acl(path: Path) -> None:
    """Sync the store's ACL again at the real clock (its config sits beside the store)."""
    config = Path(path).parent / f"{Path(path).name}-acl"
    acl.sync(path, config / "directory.json", config / "policy.json")


def new_key() -> bytes:
    """A key whose bytes are easy to find in a file (64 hex characters)."""
    return secrets.token_hex(32).encode("ascii")


@dataclass
class GateRun:
    store: Store
    bindings_id: str
    units_id: str
    log_dir: Path
    key: bytes
    process: GateProcess
    client: GateClient
    extra: list[GateProcess] = field(default_factory=list)

    @property
    def log_path(self) -> Path:
        return self.log_dir / "gate.jsonl"

    def request(self, tool: str, args: dict, facts: dict | None = None, *,
                caller: str = "user:acme-0", as_of: str = AS_OF, units: str | None = None,
                session: str = "s1") -> dict:
        return {"session": session, "caller": caller, "tool": tool, "args": args,
                "as_of": as_of, "facts": facts or {}, "units": units or self.units_id}

    def start(self, **kw) -> GateProcess:
        """Another gate on this store and log (stop the running one first)."""
        p = GateProcess(self.store.path, kw.pop("bindings_id", self.bindings_id),
                        kw.pop("log_dir", self.log_dir), kw.pop("socket_path",
                                                                 self.process.socket_path),
                        kw.pop("key", self.key), deadline=kw.pop("deadline", DEADLINE), **kw)
        self.extra.append(p)
        return p


def start_gate(store: Store, work: Path, *, key: bytes | None = None,
               deadline: float = DEADLINE) -> GateRun:
    fresh_acl(store.path)
    bindings_id = read_bindings_head(store.path)
    key = key or new_key()
    log_dir = work / "gate-log"
    process = GateProcess(store.path, bindings_id, log_dir, private_socket(), key,
                          deadline=deadline)
    assert process.ok, process.error
    return GateRun(store, bindings_id, read_units_head(store.path), log_dir, key, process,
                   GateClient(process.socket_path, key, deadline=deadline))


@pytest.fixture
def gate(tmp_path):
    run = start_gate(make_units_built_with_bindings(tmp_path / "store"), tmp_path)
    try:
        yield run
    finally:
        for p in [*run.extra, run.process]:
            p.stop()
        shutil.rmtree(run.process.socket_path.parent, ignore_errors=True)
