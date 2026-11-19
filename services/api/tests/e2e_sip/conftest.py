"""Fixtures for the Docker SIP end-to-end test. Skipped unless ``SPARTA_SIP_E2E=1`` and Docker is available.

    python scripts/sip_e2e.py            # the usual way
    SPARTA_SIP_E2E=1 pytest tests/e2e_sip -q

The stack (real Asterisk + the Sparta API with fake speech) is built and started once per session and removed afterwards.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sip_stack import Stack

SPEECH = os.environ.get(
    "SPARTA_SIP_E2E_SPEECH", "fake"
)  # "fake": tone-coded test speech; "local": real Whisper and Piper
SPEECH_TESTS = "test_local_speech_sip.py"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    enabled = os.environ.get("SPARTA_SIP_E2E") == "1" and shutil.which("docker")
    no_docker = pytest.mark.skip(reason="needs Docker and SPARTA_SIP_E2E=1 (run: python scripts/sip_e2e.py)")
    other_mode = pytest.mark.skip(
        reason="belongs to the other speech mode (python scripts/sip_e2e.py [--speech local])"
    )
    for item in items:
        if "e2e_sip" not in str(item.path):
            continue
        if not enabled:
            item.add_marker(no_docker)
        elif (SPEECH == "local") != (item.path.name == SPEECH_TESTS):
            item.add_marker(other_mode)


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    docker = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    if docker.returncode != 0:
        pytest.skip("the Docker daemon is not running")
    if SPEECH == "local":
        directory = os.environ.get("SPARTA_LOCAL_MODEL_DIR")
        if not directory:
            pytest.skip("SPARTA_LOCAL_MODEL_DIR is not set (python scripts/sip_e2e.py --speech local --models DIR)")
        instance = Stack(
            stt="local",
            tts="local",
            models_dir=Path(directory),
            max_call_seconds=int(os.environ.get("SPARTA_SIP_E2E_MAX_CALL_S", "90")),
        )
    else:
        instance = Stack(max_call_seconds=int(os.environ.get("SPARTA_SIP_E2E_MAX_CALL_S", "30")))
    try:
        instance.up()
        yield instance
    finally:
        # Keep the container output when asked, for debugging a failed run.
        keep = os.environ.get("SPARTA_SIP_E2E_KEEP_LOGS")
        if keep:
            Path(keep).write_text(instance.logs(), encoding="utf-8")
        instance.down()


@pytest.fixture(scope="session")
def evidence() -> Iterator[list[dict[str, Any]]]:
    """Measurements collected by the tests; written to ``SPARTA_WRITE_EVIDENCE`` (if set) at the end of the session."""
    rows: list[dict[str, Any]] = []
    yield rows
    path = os.environ.get("SPARTA_WRITE_EVIDENCE")
    if path:
        speech = (
            "REAL local speech (faster-whisper small, CPU int8, and Piper); the caller is a synthetic Piper voice, not a person"
            if SPEECH == "local"
            else "fake tone-coded speech; NOT real speech recognition"
        )
        Path(path).write_text(
            json.dumps(
                {
                    "kind": "sip_e2e",
                    "speech": SPEECH,
                    "label": "local SIP: real Asterisk, real SIP/RTP/G.711, headless baresip caller (a container on the same "
                    f"Docker network); {speech}; NOT a physical phone",
                    "results": rows,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
