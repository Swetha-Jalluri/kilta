import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest
import uvicorn

from kilta_bridge.app import clear_runtime_data, create_app
from kilta_bridge.chain import FallbackModel, Link, build_chain
from kilta_bridge.config import REPO_ROOT, Settings

SERVER_DIR = REPO_ROOT / "server"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


@dataclass
class McpServer:
    url: str
    data_dir: Path


@pytest.fixture(scope="module")
def mcp_server(tmp_path_factory) -> Iterator[McpServer]:
    """The real Kilta MCP server on a random free port, with a throwaway copy of the data."""
    data = tmp_path_factory.mktemp("kilta") / "data"
    shutil.copytree(REPO_ROOT / "data", data, ignore=shutil.ignore_patterns("sessions", "state"))
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["KILTA_DATA_DIR"] = str(data)
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--frozen",
            "--project",
            str(SERVER_DIR),
            "kilta-server",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if not wait_for_port(port):
        proc.kill()
        pytest.fail(f"server did not start:\n{proc.stdout.read()}")
    yield McpServer(f"http://127.0.0.1:{port}/mcp", data)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(autouse=True)
def clean_server_data(request) -> None:
    if "mcp_server" in request.fixturenames:
        server = request.getfixturevalue("mcp_server")
        clear_runtime_data(server.data_dir)


@dataclass
class Bridge:
    url: str
    app: object
    chain: FallbackModel
    mcp: McpServer

    def turn(self, text: str, member: str | None = "priya", language: str | None = None) -> dict:
        body = {"text": text, "member_id": member, "language": language}
        r = httpx.post(f"{self.url}/api/turn", json=body, timeout=450)
        assert r.status_code == 200, r.text
        return r.json()


BridgeFactory = Callable[..., Bridge]


@pytest.fixture
def start_bridge(mcp_server: McpServer) -> Iterator[BridgeFactory]:
    """Run the real bridge app (uvicorn in a thread) around a given model chain."""
    running: list[tuple[uvicorn.Server, threading.Thread]] = []

    def factory(
        links: list[Link] | None = None,
        *,
        settings: Settings | None = None,
        demo_mode: bool = True,
        mcp_url: str | None = None,
        sse_keepalive: float = 15.0,
        **chain_kwargs,
    ) -> Bridge:
        """Pass `links` for a fake chain, or `settings` to build the real chain from them."""
        if settings is None:
            settings = Settings(
                mcp_url=mcp_url or mcp_server.url,
                data_dir=mcp_server.data_dir,
                demo_mode=demo_mode,
                retry_base_delay=0.0,
                sse_keepalive=sse_keepalive,
            )
            chain_kwargs.setdefault("base_delay", 0.0)
            chain = FallbackModel(links or [], **chain_kwargs)
        else:
            settings = replace(settings, mcp_url=mcp_server.url, data_dir=mcp_server.data_dir)
            chain = build_chain(settings)
        app = create_app(settings, chain)
        port = free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        assert wait_for_port(port, 10), "bridge did not start"
        running.append((server, thread))
        return Bridge(f"http://127.0.0.1:{port}", app, chain, mcp_server)

    yield factory
    for server, thread in running:
        server.should_exit = True
        thread.join(timeout=5)
