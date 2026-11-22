"""The environment of one simulation trial, as the agent loop sees it (Phase 4 spec §13.1;
Task 20): `ProcessEnv` is the environment process (`python -m adr_eval.sim.env`, JSON lines),
the default; `LocalEnv` runs the same `env.Env` in this process (tests), its results passed
through JSON so both render the same bytes. Both have `store_path`, `first_message`,
`call(tool, args)`, `close() -> end state` (idempotent) and `log_lines()`. The factories log a
trial to `<root>/<arm>/<task>/t<trial>`. The procedure runtime runs inside the environment
(`env.Env`: forced on in arm `gate-runtime`, elsewhere on when the given `profile` is enabled
in `runtime_config`, Task 21), so with `ProcessEnv` it runs in the environment process, never
in the agent loop (N13). `ProcessEnv` passes the profile and the config path (resolved here:
default `runtime.RUNTIME_CONFIG`) on the process's command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adr_eval.sim import env as env_mod
from adr_eval.sim import runtime as runtime_mod
from adr_eval.sim import user
from adr_eval.sim.tasks import SimError, SimTask

__all__ = ["LocalEnv", "ProcessEnv", "local_env_factory", "process_env_factory", "trial_dir"]


def _plain(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


class LocalEnv:
    """`env.Env` in this process, with the process's interface (results as plain JSON)."""

    def __init__(self, store_path: Path, task: SimTask, arm: str, log_dir: Path, *,
                 profile: str | None = None, runtime_config: Path | None = None):
        self.store_path = Path(store_path)
        self._env = env_mod.Env(self.store_path, task, arm, log_dir, profile=profile,
                                runtime_config=runtime_config)
        self.first_message = user.first_message(task)
        self._end: dict | None = None
        self._closed = False

    def call(self, tool: Any, args: Any) -> dict:
        return _plain(self._env.call(tool, args))

    def close(self) -> dict:
        if not self._closed:
            self._closed = True
            self._end = _plain(self._env.world.end_state())
            self._env.close()
        return self._end

    def log_lines(self) -> list[dict]:
        return self._env.log_lines()


class ProcessEnv:
    """The environment process of one trial (`python -m adr_eval.sim.env`, JSON lines)."""

    def __init__(self, store_path: Path, task: SimTask, arm: str, log_dir: Path, *,
                 profile: str | None = None, runtime_config: Path | None = None):
        self.store_path = Path(store_path)
        self.log_path = Path(log_dir) / "env.jsonl"
        self._end: dict | None = None
        self._closed = False
        flags = ["--runtime-config", str(runtime_config or runtime_mod.RUNTIME_CONFIG)]
        if profile is not None:
            flags += ["--profile", profile]
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "adr_eval.sim.env", "--store", str(self.store_path),
             "--log", str(log_dir), *flags], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8",
            env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"})
        try:
            first = self._ask({"task": task.model_dump(by_alias=True, mode="json"),
                               "arm": arm})
        except BaseException:
            self._kill()
            raise
        if not first.get("ready"):
            self._kill()
            raise SimError(f"the environment did not start: {first.get('error')}")
        self.first_message = first["first_message"]

    def _ask(self, msg: dict) -> dict:
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise SimError(f"the environment process ended (exit {self._proc.poll()})")
        return json.loads(line)

    def _kill(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
        for f in (self._proc.stdin, self._proc.stdout):
            f.close()

    def call(self, tool: Any, args: Any) -> dict:
        return self._ask({"tool": tool, "args": args})

    def close(self) -> dict:
        if not self._closed:
            self._closed = True
            try:
                self._end = self._ask({"end": True})["end_state"]
                self._proc.stdin.close()
                self._proc.wait(timeout=120)
            finally:
                self._kill()
        return self._end

    def log_lines(self) -> list[dict]:
        return [json.loads(x) for x in self.log_path.read_bytes().splitlines()]


def trial_dir(root: Path, task_id: str, arm: str, trial: int) -> Path:
    return Path(root) / arm / task_id / f"t{trial}"


def local_env_factory(store_path: Path, root: Path, *, profile: str | None = None,
                      runtime_config: Path | None = None) -> Callable:
    """`(task, arm, trial) -> LocalEnv` logging to `root/<arm>/<task>/t<trial>`."""
    def make(task: SimTask, arm: str, trial: int) -> LocalEnv:
        return LocalEnv(store_path, task, arm, trial_dir(root, task.task_id, arm, trial),
                        profile=profile, runtime_config=runtime_config)
    return make


def process_env_factory(store_path: Path, root: Path, *, profile: str | None = None,
                        runtime_config: Path | None = None) -> Callable:
    """`(task, arm, trial) -> ProcessEnv` logging to `root/<arm>/<task>/t<trial>`: one
    environment process (`python -m adr_eval.sim.env`) per trial, the runtime inside it."""
    def make(task: SimTask, arm: str, trial: int) -> ProcessEnv:
        return ProcessEnv(store_path, task, arm, trial_dir(root, task.task_id, arm, trial),
                          profile=profile, runtime_config=runtime_config)
    return make
