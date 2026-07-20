import os
import pytest
from pathlib import Path
from myphoto.paths import (
    PathTraversalError,
    normalize_relative,
    resolve_within_root,
)


class TestNormalizeRelative:
    def test_empty_string_returns_empty(self):
        assert normalize_relative("") == ""

    def test_strips_leading_slash(self):
        assert normalize_relative("/a/b") == "a/b"

    def test_converts_backslashes(self):
        assert normalize_relative("a\\b\\c") == "a/b/c"

    def test_collapses_double_slashes(self):
        assert normalize_relative("a//b///c") == "a/b/c"

    def test_removes_current_dir_segments(self):
        assert normalize_relative("a/./b") == "a/b"

    def test_rejects_parent_dir_segment(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("a/../b")

    def test_rejects_absolute_windows_drive(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("C:/x")

    def test_rejects_null_byte(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("a/b\x00")


class TestResolveWithinRoot:
    def test_resolves_child(self, tmp_path):
        (tmp_path / "sub").mkdir()
        result = resolve_within_root(str(tmp_path), "sub")
        assert result == (tmp_path / "sub").resolve()

    def test_rejects_traversal_via_symlink(self, tmp_path):
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "sneaky"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported")
        with pytest.raises(PathTraversalError):
            resolve_within_root(str(tmp_path), "sneaky")

    def test_rejects_parent_segment(self, tmp_path):
        with pytest.raises(PathTraversalError):
            resolve_within_root(str(tmp_path), "../etc")

    def test_empty_rel_returns_root(self, tmp_path):
        assert resolve_within_root(str(tmp_path), "") == tmp_path.resolve()
