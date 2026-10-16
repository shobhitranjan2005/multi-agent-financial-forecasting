"""Unit tests for provenance hashing and git_dirty rules (P2 & P3)."""
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.eval import provenance


def test_sha256_normalizes_crlf_to_lf(tmp_path):
    f_crlf = tmp_path / "crlf.json"
    f_lf = tmp_path / "lf.json"

    f_crlf.write_bytes(b'{\r\n  "key": "value"\r\n}\r\n')
    f_lf.write_bytes(b'{\n  "key": "value"\n}\n')

    assert provenance._sha256(f_crlf) == provenance._sha256(f_lf)


def test_sha256_testset_draft_v3_matches_head():
    draft = Path("data/testset_draft_v3.json")
    if draft.exists():
        # Canonical LF hash from GitHub / HEAD
        assert provenance._sha256(draft) == "e39446db5c3058622d0512637558352ea057fcb20bdaa7d5f70e7427d7f567c0"


@pytest.mark.parametrize(
    "porcelain, expected_dirty",
    [
        ("", False),
        # Everything under results/ (tracked or untracked) must NOT make the tree dirty
        (" M results/runner_progress.json\n", False),
        ("M  results/runner_progress.json\n", False),
        ("MM results/runner_progress.json\n", False),
        ("D  results/runner_progress.json\n", False),
        (" M results/baseline_20261017.csv\n", False),
        ("?? results/prefetch_progress.json\n", False),
        ("?? results/preflight_20261016_142558.json\n", False),
        ("R  results/old.json -> results/superseded_testset_v1/old.json\n", False),
        ("R  results/old.json -> backend/moved.json\n", True),
        # Any database or WAL/SHM file under data/ must NOT make the tree dirty
        ("?? data/cache.db\n", False),
        ("?? data/cache.db-wal\n?? data/cache.db-shm\n", False),
        (" M data/cache.db\n", False),
        (" M data/graph_checkpoints.db-wal\n", False),
        ("?? results/sub/deep.json\n?? data/custom_cache.db\n", False),
        # Modified tracked source/config files must count as dirty
        (" M docs/LIMITATIONS.md\n", True),
        ("M  backend/llm.py\n", True),
        (" M backend/eval/runner.py\n", True),
        ("D  backend/old.py\n", True),
        # Untracked source files elsewhere must count as dirty
        ("?? backend/eval/new_eval.py\n", True),
        ("?? tests/test_new.py\n", True),
        ("?? new_script.py\n", True),
        ("?? data/new_universe.py\n", True),
        # Mixture of ignored and non-ignored
        (" M results/runner_progress.json\n M backend/llm.py\n", True),
        ("?? results/progress.json\n M backend/llm.py\n", True),
        ("?? results/progress.json\n?? backend/foo.py\n", True),
    ],
)
def test_is_git_dirty_rules(porcelain, expected_dirty):
    with patch("backend.eval.provenance._git", return_value=porcelain):
        assert provenance.is_git_dirty() is expected_dirty
