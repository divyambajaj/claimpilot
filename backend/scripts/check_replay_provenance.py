"""Fail if any replay recording was made from an image that is not a committed synthetic fixture.

Recordings store only image sha256s (`request_meta.images[].id = "{sha256}:{page}"`); every one must match a
file under the demo gallery, the eval fixtures or the test fixtures. Keeps personal receipts out of the repo.

    uv run python backend/scripts/check_replay_provenance.py   # part of `make lint` and CI
"""

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY = REPO_ROOT / "data" / "replay"
ALLOWED = [
    REPO_ROOT / "data" / "demo_receipts",
    REPO_ROOT / "data" / "eval" / "fixtures",
    REPO_ROOT / "backend" / "tests" / "fixtures",
]


def known_shas(dirs: list[Path]) -> set[str]:
    return {
        hashlib.sha256(p.read_bytes()).hexdigest()
        for d in dirs
        if d.exists()
        for p in d.rglob("*")
        if p.is_file()
    }


def unknown_recordings(replay_dir: Path, dirs: list[Path]) -> list[str]:
    shas = known_shas(dirs)
    bad = []
    for path in sorted(replay_dir.glob("*.json")):
        images = json.loads(path.read_text()).get("request_meta", {}).get("images", [])
        missing = [i["id"] for i in images if i["id"].split(":")[0] not in shas]
        if missing:
            bad.append(f"{path.name}: image {', '.join(missing)} is not a committed fixture")
    return bad


def main() -> int:
    bad = unknown_recordings(REPLAY, ALLOWED)
    for line in bad:
        print(line, file=sys.stderr)
    if bad:
        print(
            f"{len(bad)} replay file(s) were recorded from non-fixture images; delete them", file=sys.stderr
        )
        return 1
    print(f"replay provenance ok ({len(list(REPLAY.glob('*.json')))} recordings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
