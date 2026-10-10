"""The replay provenance guard (backend/scripts/check_replay_provenance.py)."""

import hashlib
import importlib.util
import json
from pathlib import Path

from app.config import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "check_replay_provenance", REPO_ROOT / "backend" / "scripts" / "check_replay_provenance.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _record(replay: Path, name: str, sha: str) -> None:
    meta = {"request_meta": {"images": [{"id": f"{sha}:0"}]}}
    (replay / f"{name}.json").write_text(json.dumps(meta))


def test_flags_recordings_of_unknown_images(tmp_path: Path) -> None:
    fixtures, replay = tmp_path / "fixtures", tmp_path / "replay"
    (fixtures / "sub").mkdir(parents=True)
    replay.mkdir()
    (fixtures / "sub" / "a.png").write_bytes(b"synthetic")
    _record(replay, "ok", hashlib.sha256(b"synthetic").hexdigest())
    (replay / "compile.json").write_text(json.dumps({"request_meta": {"images": []}}))
    assert guard.unknown_recordings(replay, [fixtures, tmp_path / "absent"]) == []
    _record(replay, "personal", "f" * 64)
    assert guard.unknown_recordings(replay, [fixtures]) == [
        f"personal.json: image {'f' * 64}:0 is not a committed fixture"
    ]


def test_committed_recordings_are_all_fixtures() -> None:
    assert guard.main() == 0
