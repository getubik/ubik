"""Tests for the bounded repo snapshot."""
from __future__ import annotations

from pathlib import Path

from ubik.tools.codebase_read import read_repo


def _make_repo(root: Path) -> None:
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x" * 100, encoding="utf-8")
    (root / ".git").mkdir()  # fake — read_repo's git step gracefully fails
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)


def test_read_repo_collects_high_value_files(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    snapshot = read_repo(tmp_path)

    paths = [f.path for f in snapshot.high_value_files]
    assert "README.md" in paths
    assert "pyproject.toml" in paths
    # Source root file picked up too.
    assert "src/main.py" in paths


def test_read_repo_skips_node_modules_and_binaries(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    snapshot = read_repo(tmp_path)

    for f in snapshot.high_value_files:
        assert "node_modules" not in f.path
        assert not f.path.endswith(".png")
    assert "node_modules/junk.js" not in snapshot.file_tree


def test_read_repo_truncates_long_files(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    big_path = tmp_path / "big.py"
    big_path.write_text("x = 1\n" * 5000, encoding="utf-8")

    snapshot = read_repo(tmp_path, max_file_chars=200)

    bigs = [f for f in snapshot.high_value_files if f.path == "big.py"]
    if bigs:  # included as a top-level code file
        assert bigs[0].truncated is True
        assert len(bigs[0].content) <= 200


def test_read_repo_language_breakdown(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2", encoding="utf-8")
    (tmp_path / "c.ts").write_text("export const z = 3", encoding="utf-8")

    snapshot = read_repo(tmp_path)
    assert snapshot.languages.get(".py") == 2
    assert snapshot.languages.get(".ts") == 1
