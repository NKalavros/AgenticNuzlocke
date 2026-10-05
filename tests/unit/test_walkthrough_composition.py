import json

import pytest

from nuzlocke.knowledge.walkthrough import compose, skill_dir


def manifest(root, *, fragments=None, bundles=None):
    (root / "manifest.json").write_text(json.dumps({"fragments": fragments or {}, "bundles": bundles or {}}))


def test_order_nested_bundles_and_deduplication(tmp_path):
    manifest(
        tmp_path,
        fragments={"a": "a.md", "b": "b.md", "unused": "absent.md"},
        bundles={"first": ["b", "a"], "second": ["first", "b"]},
    )
    (tmp_path / "a.md").write_text("A")
    (tmp_path / "b.md").write_text("B")
    assert compose("second", "a", root=tmp_path) == "B\n\nA"


def test_cycles_and_unknown_sections_fail_clearly(tmp_path):
    manifest(tmp_path, bundles={"a": ["b"], "b": ["a"]})
    with pytest.raises(ValueError, match="include cycle: a -> b -> a"):
        compose("a", root=tmp_path)
    with pytest.raises(KeyError, match="missing"):
        compose("missing", root=tmp_path)


def test_fragment_cannot_escape_root(tmp_path):
    manifest(tmp_path, fragments={"escape": "../outside.md"})
    with pytest.raises(ValueError, match="escapes its root"):
        compose("escape", root=tmp_path)


def test_length_limit_and_invalid_budget(tmp_path):
    manifest(tmp_path, fragments={"a": "a.md"})
    (tmp_path / "a.md").write_text("Long guidance " * 30)
    for limit in (0, 1, 5, 20, 50):
        assert len(compose("a", root=tmp_path, max_chars=limit)) <= limit
    with pytest.raises(ValueError, match="nonnegative"):
        compose("a", root=tmp_path, max_chars=-1)


def test_all_fragments_preserve_compatibility_guide_and_stages_are_selective():
    root = skill_dir()
    assert compose("all").split() == (root / "reference.md").read_text().split()
    guide = json.loads((root / "manifest.json").read_text())
    for chapter in ("surge", "erika"):
        for bundle in guide["bundles"]:
            if bundle.startswith(chapter + "."):
                assert 0 < len(compose(bundle)) < len(compose(chapter))
