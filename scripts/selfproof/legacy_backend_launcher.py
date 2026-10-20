"""T05 / S-6 — launch the **real** legacy backend, wrapped so every response is
attributable to the process this runner spawned.

Two roles in one file (design §3.2 keeps both here so the wrapper diff is
reviewable in one place):

``python legacy_backend_launcher.py --serve``
    **Child.**  Puts the 32 ``*/src`` roots on ``sys.path``, imports the real
    ``wbtime_ai_api.main:app``, installs the scripted model provider + fake
    sandbox (reusing ``_old/tests/e2e/fixtures/wiring.py`` — *not* reimplemented),
    wraps the app in :class:`NonceWrapper` and hands it to uvicorn.

:class:`BackendProcess`
    **Parent.**  Spawns the child, polls ``/health``, reads ``/__e2e__/attest``,
    counts ``session`` rows and kills the process with SIGTERM.

The wording red line (裁定 D-1 — quote it verbatim in the ledger)
----------------------------------------------------------------
    该响应头由**我们仓内的包装层**产生，证明的是「**这条响应来自本 runner spawn
    的那个进程**」，**不等于**「Python 后端自身实现了 nonce 协议」。
    V0.1.0+ TS 后端应由后端自身回该头，届时**包装层必须自动退场**。

The auto-retire half of D-1 is implemented **dynamically**: :class:`NonceWrapper`
adds ``X-E2E-Nonce`` only when the inner response did **not** already carry it.  A
backend that implements the header itself therefore wins, the wrapper marks
``retired`` and prints ``wrapper: not needed (backend implements X-E2E-Nonce)``
once; the attestation payload reports the same state, so the ledger can never
claim the wrapper was load-bearing when it was not.

Read-only discipline (G-4, violated => 53)
------------------------------------------
* ``sys.dont_write_bytecode = True`` **before** importing anything from ``_old``
  (plus ``-B`` and ``PYTHONDONTWRITEBYTECODE=1`` from the parent);
* ``os.chdir(workdir)`` — never ``_old``: the relative default DSN
  ``sqlite:///./wbtime-ai_local.db`` would otherwise write into the read-only tree;
* only the **database file** is copied (never the tree, never ``.venv``);
* the absolute DSN is passed explicitly.

Exit codes (§3.3): ``0`` normal, ``51`` launch timeout, ``52`` port busy,
``53`` read-only tree written during boot, ``2`` usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

_SELF_DIR: Final[Path] = Path(__file__).resolve().parent
_SCRIPTS_DIR: Final[Path] = _SELF_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (shared primitives only)

__all__ = [
    "TAG",
    "NONCE_HEADER",
    "NONCE_ENV",
    "ATTEST_PATH",
    "DEFAULT_PORT",
    "Attestation",
    "BackendProcess",
    "resolve_legacy_root",
    "resolve_legacy_python",
    "check_prerequisites",
    "main",
]

#: Log tag (K-7).
TAG: Final[str] = "selfproof"

#: Nonce response header (K-1).
NONCE_HEADER: Final[str] = "X-E2E-Nonce"

#: Lower-case form used for ASGI header matching (ASGI headers are bytes, lowercase).
NONCE_HEADER_LOWER: Final[str] = NONCE_HEADER.lower()

#: Nonce environment variable (K-2): only ever lives in memory / child env.
NONCE_ENV: Final[str] = "E2E_RUN_NONCE"

#: Attestation endpoint, answered by the wrapper (never entered into the OpenAPI
#: route table, so ``compare_openapi --candidate url`` cannot see it — K-3).
ATTEST_PATH: Final[str] = "/__e2e__/attest"

#: Default port (K-5); forward and reverse must use the same one.
DEFAULT_PORT: Final[int] = 8099

#: SQLite table holding sessions — **singular** ``session`` (裁定 D-3).
SESSION_TABLE: Final[str] = "session"

#: Sandbox stdout used by the fake sandbox.
FAKE_STDOUT: Final[str] = "hello\n"


# ---------------------------------------------------------------------------
# Prerequisites / path resolution
# ---------------------------------------------------------------------------


def resolve_legacy_root(override: str | Path | None = None) -> Path:
    """Resolve the read-only legacy tree (G-1).

    Args:
        override: Explicit path (CLI / test harness).

    Returns:
        The legacy root; callers must verify it exists.
    """
    if override:
        return Path(override).expanduser().resolve()
    return _gate_io.GatePaths.resolve().legacy_root


def resolve_legacy_python(legacy_root: Path, override: str | Path | None = None) -> Path:
    """Resolve the interpreter that can import fastapi / uvicorn / sqlalchemy (G-2).

    Args:
        legacy_root: Read-only legacy tree.
        override: Explicit interpreter path.

    Returns:
        The interpreter path (may not exist — :func:`check_prerequisites` checks).
    """
    if override:
        return Path(override).expanduser().resolve()
    windows = legacy_root / ".venv" / "Scripts" / "python.exe"
    if windows.is_file():
        return windows
    posix = legacy_root / ".venv" / "bin" / "python"
    if posix.is_file():
        return posix
    return windows


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """Whether ``port`` can be bound right now (G-5).

    Args:
        port: TCP port.
        host: Bind address.

    Returns:
        ``True`` when the port is free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def check_prerequisites(
    *,
    legacy_root: Path | None = None,
    python: Path | None = None,
    port: int = DEFAULT_PORT,
    require_port: bool = True,
) -> list[str]:
    """Run the G-1 / G-2 / G-3 / G-5 preconditions.

    Args:
        legacy_root: Override for the legacy root.
        python: Override for the legacy interpreter.
        port: Port the backend will listen on.
        require_port: Whether the port must be free (the reverse leg does not).

    Returns:
        Human readable problems; empty means "segment II may start".
    """
    problems: list[str] = []
    root = legacy_root or resolve_legacy_root()
    if not root.is_dir():
        problems.append(f"G-1: legacy root missing: {root.as_posix()}")
        return problems
    src_roots = sorted((root / "packages").glob("*/src")) + sorted((root / "apps").glob("*/src"))
    if len(src_roots) < 30:
        problems.append(f"G-1: expected >=30 '*/src' roots, found {len(src_roots)}")
    interpreter = python or resolve_legacy_python(root)
    if not interpreter.is_file():
        problems.append(f"G-2: legacy interpreter missing: {interpreter.as_posix()}")
    database = root / "wbtime-ai_local.db"
    if not database.is_file():
        problems.append(f"G-3: legacy database missing: {database.as_posix()}")
    if require_port and not _port_is_free(port):
        problems.append(f"G-5: port {port} is already in use")
    node = shutil.which("node")
    if node is None:
        problems.append("G-6: node is not on PATH")
    return problems


def count_session_rows(database: Path) -> int:
    """Return ``select count(*) from session`` on a **read-only** connection.

    Args:
        database: SQLite file (the copy, never the read-only original).

    Returns:
        The row count, or ``-1`` when the query cannot run (reported, not guessed).
    """
    if not database.is_file():
        return -1
    uri = f"file:{database.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            row = connection.execute(f"select count(*) from {SESSION_TABLE}").fetchone()
            return int(row[0]) if row is not None else -1
        finally:
            connection.close()
    except sqlite3.Error:
        return -1


# ---------------------------------------------------------------------------
# Child: the wrapped ASGI app
# ---------------------------------------------------------------------------


class NonceWrapper:
    """ASGI wrapper that stamps ``X-E2E-Nonce`` on every HTTP response.

    It also answers :data:`ATTEST_PATH` itself, so the attestation never becomes
    part of the backend's public contract (K-3).  When the inner application
    already emits the header the wrapper **steps aside** (D-1 auto-retire).
    """

    def __init__(self, inner: Any, nonce: str, *, started_at: float, db_url: str) -> None:
        """Store the inner app and the run identity.

        Args:
            inner: The real ASGI application (``wbtime_ai_api.main:app``).
            nonce: Run nonce from :data:`NONCE_ENV`.
            started_at: ``time.time()`` at process start.
            db_url: The absolute DSN the backend was told to use.
        """
        self.inner = inner
        self.nonce = nonce
        self.started_at = started_at
        self.db_url = db_url
        self.retired = False

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """ASGI entry point.

        Args:
            scope: ASGI scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        if scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return

        if scope.get("path") == ATTEST_PATH and scope.get("method") == "GET":
            body = json.dumps(
                {
                    "nonce": self.nonce,
                    "pid": os.getpid(),
                    "ppid": os.getppid(),
                    "started_at": self.started_at,
                    "db": self.db_url,
                    "cwd": os.getcwd(),
                    "wrapper": "retired" if self.retired else "active",
                    "note": (
                        "X-E2E-Nonce is produced by this launcher wrapper: it proves the "
                        "response came from the process this runner spawned, NOT that the "
                        "Python backend implements a nonce protocol (D-1)"
                    ),
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (NONCE_HEADER_LOWER.encode(), self.nonce.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                names = {name.decode("latin-1").lower() for name, _ in headers}
                if NONCE_HEADER_LOWER in names:
                    if not self.retired:
                        self.retired = True
                        print(
                            "wrapper: not needed (backend implements X-E2E-Nonce)",
                            flush=True,
                        )
                else:
                    headers.append((NONCE_HEADER_LOWER.encode(), self.nonce.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.inner(scope, receive, send_wrapper)


def _install_scripted_doubles(app: Any) -> str:
    """Replace the model provider and sandbox with deterministic doubles.

    Reuses ``_old/tests/e2e/fixtures`` (read-only import) exactly as the design
    prescribes (§1.2.1) — the transport is ours, the fixtures are theirs.

    Args:
        app: The real FastAPI application (lifespan already completed).

    Returns:
        A one-line description for the boot log.
    """
    from tests.e2e.fixtures.fake_sandbox import FakeSandboxProvider
    from tests.e2e.fixtures.stub_provider_script import tool_call_content
    from tests.e2e.fixtures.wiring import install_scripted_runtime_on_services, seed_builtin_tool

    script = [tool_call_content("shell", {"command": "echo hello"}), "All done: hello"]
    # A third turn that is *again* a tool call: ``ScriptedModelProvider`` repeats
    # the last entry forever, so every run after the first keeps requesting a tool
    # and ends in MAX_ITERATIONS -> agent.failed -> the ``agent.error`` channel.
    script.append(tool_call_content("shell", {"command": "echo again"}))
    doubles = install_scripted_runtime_on_services(
        app.state.services, script, sandbox=FakeSandboxProvider(stdout=FAKE_STDOUT)
    )
    tool_id = seed_builtin_tool(app.state.services, name="shell")
    return f"scripted provider={doubles.model_config} tool_id={tool_id}"


def serve(port: int, workdir: Path, legacy_root: Path, nonce: str) -> int:
    """Child process body: boot the real backend behind the wrapper.

    Args:
        port: TCP port to bind.
        workdir: Working directory (outside the legacy tree).
        legacy_root: Read-only legacy tree.
        nonce: Run nonce from the environment.

    Returns:
        ``0`` on a clean shutdown, ``52`` when the port was taken.
    """
    if not nonce:
        print(f"[{TAG}] ERROR: {NONCE_ENV} is not set (K-2)", flush=True)
        return _gate_io.EXIT_USAGE
    if not _port_is_free(port):
        print(f"[{TAG}] ERROR: port {port} already in use (G-5)", file=sys.stderr, flush=True)
        return _gate_io.EXIT_PORT_BUSY

    workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(workdir)  # G-4: never inside the read-only tree

    database_copy = workdir / "run.db"
    source_database = legacy_root / "wbtime-ai_local.db"
    shutil.copy2(source_database, database_copy)  # only the DB, never the tree

    os.environ["WBTIME_AI_MODE"] = "local"
    os.environ["WBTIME_AI_DATABASE_URL"] = f"sqlite:///{database_copy.as_posix()}"
    os.environ["WBTIME_AI_DATA_DIR"] = str(workdir / "data")
    os.environ["WBTIME_AI_WORKSPACE_ROOT"] = str(workdir / "ws")
    os.environ.setdefault("WBTIME_AI_SECRET_KEY", "e2e-" + nonce * 2)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    for root in ("packages", "apps"):
        for src in sorted((legacy_root / root).glob("*/src")):
            sys.path.insert(0, str(src))
    sys.path.insert(0, str(legacy_root))  # read-only reuse of tests.e2e.fixtures

    import uvicorn  # noqa: E402  (import after sys.path is complete)
    from wbtime_ai_api.main import app as real_app  # noqa: E402

    from contextlib import asynccontextmanager

    original_lifespan = real_app.router.lifespan_context

    @asynccontextmanager
    async def _lifespan(app: Any):  # noqa: ANN202 - ASGI lifespan signature
        async with original_lifespan(app) as state:
            description = _install_scripted_doubles(app)
            print(f"[{TAG}] doubles installed: {description}", flush=True)
            yield state

    real_app.router.lifespan_context = _lifespan

    wrapper = NonceWrapper(
        real_app,
        nonce,
        started_at=time.time(),
        db_url=os.environ["WBTIME_AI_DATABASE_URL"],
    )
    print(
        f"[{TAG}] serving pid={os.getpid()} port={port} cwd={os.getcwd()} "
        f"db={os.environ['WBTIME_AI_DATABASE_URL']}",
        flush=True,
    )
    uvicorn.run(wrapper, host="127.0.0.1", port=port, log_level="warning")
    return _gate_io.EXIT_OK


# ---------------------------------------------------------------------------
# Parent: BackendProcess
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attestation:
    """What the wrapper says about itself (design §3.1 ``Attestation``).

    Attributes:
        nonce: The run nonce echoed back by the wrapper.
        pid: The serving process id.
        started_at: ``time.time()`` of the serving process.
        db_url: The absolute DSN the backend used.
        session_rows: ``count(*) from session`` on the database copy.
        wrapper: ``active`` or ``retired`` (D-1 auto-retire state).
        cwd: The working directory of the serving process.
    """

    nonce: str
    pid: int
    started_at: float
    db_url: str
    session_rows: int
    wrapper: str
    cwd: str
    ppid: int = -1

    def render(self) -> str:
        """Return a one-line evidence rendering (never contains the raw nonce).

        Returns:
            ``"pid=... started_at=... session_rows=... wrapper=... db=..."``.
        """
        return (
            f"pid={self.pid} ppid={self.ppid} started_at={self.started_at:.3f} "
            f"session_rows={self.session_rows} wrapper={self.wrapper} db={self.db_url}"
        )


class BackendProcess:
    """Parent-side handle on one spawned backend (design §3.1).

    Responsibilities: spawn, wait for ``/health``, attest, SIGTERM, and never write
    into the read-only tree (G-4).
    """

    def __init__(
        self,
        *,
        port: int,
        nonce: str,
        db_source: Path,
        workdir: Path,
        script: Sequence[str] | None = None,
        scenario: str = "s-main",
        python: Path | None = None,
        legacy_root: Path | None = None,
    ) -> None:
        """Record everything needed to spawn the child.

        Args:
            port: TCP port.
            nonce: Run nonce (also exported to the child as :data:`NONCE_ENV`).
            db_source: The read-only legacy database (only it is copied).
            workdir: Scratch directory outside the read-only tree.
            script: Reserved for scenario scripting; the doubles are installed by
                the child from ``_old/tests/e2e/fixtures`` and the third turn is
                always a tool call, so ``s-main`` and ``s-error`` share one boot.
            scenario: Scenario label carried into the log/attestation lineage.
            python: Interpreter override (needs fastapi/uvicorn — the legacy venv).
            legacy_root: Legacy tree override.
        """
        self.port = int(port)
        self.nonce = nonce
        self.db_source = Path(db_source)
        self.workdir = Path(workdir)
        self.script = tuple(script or ())
        self.scenario = scenario
        self.legacy_root = Path(legacy_root) if legacy_root else resolve_legacy_root()
        self.python = Path(python) if python else resolve_legacy_python(self.legacy_root)
        self._process: subprocess.Popen[str] | None = None
        self._log_lines: list[str] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self, *, timeout_s: float = 60.0) -> None:
        """Spawn the child and wait until ``/health`` answers 200.

        Args:
            timeout_s: Hard limit for the boot (exceeded => ``EXIT_LAUNCH_TIMEOUT``).

        Raises:
            TimeoutError: The backend did not become healthy in time (51).
            OSError: The child could not be spawned.
            PermissionError: The port was taken (52).
        """
        if not _port_is_free(self.port):
            raise PermissionError(f"port {self.port} is already in use")
        self.workdir.mkdir(parents=True, exist_ok=True)

        environment = dict(os.environ)
        environment[NONCE_ENV] = self.nonce
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["E2E_SCENARIO"] = self.scenario

        command = [
            str(self.python),
            "-B",
            str(Path(__file__).resolve()),
            "--serve",
            "--port",
            str(self.port),
            "--workdir",
            str(self.workdir),
            "--legacy-root",
            str(self.legacy_root),
        ]
        self._process = subprocess.Popen(
            command,
            cwd=str(self.workdir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._start_reader()

        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            if self._health_ok():
                self._drain(0.2)
                return
            if self._process.poll() is not None:
                raise TimeoutError(
                    "the backend exited during boot :: " + " | ".join(self._log_lines[-6:])
                )
            self._drain(0.2)
        self.terminate_and_wait(timeout_s=5.0)
        raise TimeoutError(
            f"backend did not answer /health within {timeout_s}s :: "
            + " | ".join(self._log_lines[-6:])
        )

    def _drain(self, budget_s: float) -> bool:
        """Wait ``budget_s`` for the reader thread to add a line.

        Windows ``select()`` does not work on pipes, so the child's stdout is read
        by :meth:`_start_reader` in a daemon thread; this method only waits for the
        next line to land (bounded by ``budget_s``).

        Args:
            budget_s: How long to wait for the next line.

        Returns:
            ``True`` when at least one new line arrived.
        """
        before = len(self._log_lines)
        deadline = time.monotonic() + max(budget_s, 0.0)
        while True:
            if len(self._log_lines) > before:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _start_reader(self) -> None:
        """Read the child's merged stdout/stderr into :attr:`_log_lines` (thread)."""
        import threading

        stream = self._process.stdout if self._process is not None else None
        if stream is None:  # pragma: no cover - defensive
            return

        def pump() -> None:
            try:
                for line in stream:
                    self._log_lines.append(line.rstrip("\r\n"))
            except (OSError, ValueError):  # pragma: no cover - closed pipe
                return

        threading.Thread(target=pump, name="e2e-backend-log", daemon=True).start()

    def _health_ok(self) -> bool:
        """Whether ``GET /health`` currently answers 200.

        Returns:
            ``True`` when the backend is up.
        """
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/health", timeout=2.0
            ) as response:
                return int(response.status) == 200
        except (urllib.error.URLError, OSError):
            return False

    def attest(self) -> Attestation:
        """Read ``/__e2e__/attest`` and attach the session-row count.

        Returns:
            The attestation.

        Raises:
            RuntimeError: The endpoint did not answer.
        """
        url = f"http://127.0.0.1:{self.port}{ATTEST_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"cannot read {ATTEST_PATH}: {error}") from error
        return Attestation(
            nonce=str(payload.get("nonce", "")),
            pid=int(payload.get("pid", -1)),
            started_at=float(payload.get("started_at", 0.0)),
            db_url=str(payload.get("db", "")),
            session_rows=count_session_rows(self.workdir / "run.db"),
            wrapper=str(payload.get("wrapper", "unknown")),
            cwd=str(payload.get("cwd", "")),
            ppid=int(payload.get("ppid", -1)),
        )

    def terminate_and_wait(self, *, timeout_s: float = 10.0) -> bool:
        """SIGTERM the child and wait until the port stops answering.

        Args:
            timeout_s: How long to wait for the socket to close.

        Returns:
            ``True`` when the port is really closed afterwards.
        """
        process = self._process
        if process is None:
            return True
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
                process.kill()
                try:
                    process.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    return False
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            if _port_is_free(self.port) and not self._health_ok():
                return True
            time.sleep(0.1)
        return False

    @property
    def pid(self) -> int:
        """The spawned process id (``-1`` when the child never started)."""
        return self._process.pid if self._process is not None else -1

    @property
    def log_lines(self) -> list[str]:
        """Everything the child printed so far (evidence, never contains the nonce)."""
        self._drain(0.0)
        return list(self._log_lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="legacy_backend_launcher.py",
        description=(
            "Launch the real legacy backend (local profile) behind an ASGI wrapper that "
            "stamps X-E2E-Nonce and answers /__e2e__/attest."
        ),
    )
    parser.add_argument("--serve", action="store_true", help="child mode: run uvicorn (blocks)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"TCP port (default {DEFAULT_PORT})")
    parser.add_argument("--workdir", type=Path, default=None, help="scratch dir outside the read-only tree")
    parser.add_argument("--legacy-root", type=Path, default=None, help="read-only legacy tree")
    parser.add_argument("--check", action="store_true", help="print the G-1..G-6 precondition report and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` / ``2`` / ``51`` / ``52`` / ``53`` (design §3.3).
    """
    parser = _build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    legacy_root = resolve_legacy_root(arguments.legacy_root)

    if arguments.check:
        problems = check_prerequisites(legacy_root=legacy_root, port=arguments.port)
        _gate_io.log(TAG, f"legacy_root={legacy_root.as_posix()}")
        _gate_io.log(TAG, f"legacy_python={resolve_legacy_python(legacy_root).as_posix()}")
        if problems:
            for problem in problems:
                _gate_io.log(TAG, f"PRECONDITION FAIL: {problem}")
            _gate_io.log(TAG, "VERDICT: BLOCKED (segment II)")
            return _gate_io.EXIT_LAUNCH_TIMEOUT
        _gate_io.log(TAG, "VERDICT: READY (G-1/G-2/G-3/G-5/G-6 satisfied)")
        return _gate_io.EXIT_OK

    if not arguments.serve:
        _gate_io.log(TAG, "ERROR: nothing to do — pass --serve (child) or --check (preconditions)")
        return _gate_io.EXIT_USAGE

    workdir = Path(arguments.workdir) if arguments.workdir else (
        _gate_io.GatePaths.resolve().workdir / "manual-run"
    )
    nonce = os.environ.get(NONCE_ENV, "").strip()
    return serve(int(arguments.port), workdir.resolve(), legacy_root, nonce)


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
