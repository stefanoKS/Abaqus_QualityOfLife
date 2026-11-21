"""Restart an actual API process while its independently started worker keeps the run."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def test_api_process_restart_with_external_worker(tmp_path):
    env = dict(os.environ, SEAL_DATA=str(tmp_path))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def launch(*arguments):
        return subprocess.Popen(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def api():
        return launch(
            "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", str(port)
        )

    def wait(fetch):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                value = fetch()
                if value:
                    return value
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        raise AssertionError("Timed out waiting for the local API or worker")

    server = api()
    stop = tmp_path / "stop-test"
    worker = launch("-m", "services.worker", "--stop-file", str(stop))
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
            project = wait(lambda: http.get("/api/projects").json())[0]
            base = {"revision": project["revision"], "token": str(uuid4())}
            mesh = http.post("/api/meshes", json=base).raise_for_status().json()
            wait(lambda: http.get("/api/jobs/" + mesh["id"]).json()["status"] == "Completed")
            labels = (
                http.post("/api/meshes/" + mesh["id"] + "/fixture/edges", json={})
                .raise_for_status()
                .json()["labels"]
            )
            http.put(
                "/api/meshes/" + mesh["id"] + "/fixture", json={"labels": labels}
            ).raise_for_status()
            deck = http.post(
                "/api/decks",
                json={"revision": project["revision"], "token": str(uuid4()), "mesh": mesh["id"]},
            ).raise_for_status().json()
            wait(lambda: http.get("/api/jobs/" + deck["id"]).json()["status"] == "Completed")
            body = {
                "revision": project["revision"],
                "token": str(uuid4()),
                "name": "Restart proof",
                "mode": "DEMO",
                "deck": deck["id"],
            }
            run = http.post("/api/runs", json=body).raise_for_status().json()
            server.terminate()
            server.wait(timeout=10)
            server = api()
            wait(lambda: http.get("/api/jobs/" + run["id"]).json()["status"] == "Completed")
            assert (
                http.get("/api/revisions/" + project["revision"]).json()["setup"]["name"]
                == project["name"]
            )
            assert (
                http.get("/api/jobs/" + run["id"] + "/artifacts/results.json").json()["mode"]
                == "DEMO"
            )
            assert len(http.get("/api/runs").json()) == 1
    finally:
        stop.touch()
        server.terminate()
        server.wait(timeout=10)
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()
