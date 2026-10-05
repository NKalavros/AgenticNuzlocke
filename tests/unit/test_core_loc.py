from tools.core_loc import LIMIT, counts, source_lines


def test_core_stays_under_source_budget():
    measured = counts()
    assert measured
    assert sum(measured.values()) < LIMIT, sorted(measured.items(), key=lambda item: -item[1])[:10]


def test_counter_excludes_only_comments_blank_lines_and_real_docstrings():
    source = '''"""Module documentation.
More documentation.
"""
# Comment

value = (
    "runtime string"  # Counts
)
def example():
    """Function documentation."""
    return value
'''
    assert source_lines(source) == 5
    assert source_lines('"""doc"""; value = 1\n') == 1
    assert source_lines('def example(): "doc"; return 1\n') == 1
    assert source_lines('"""éééééééééé"""; x = 1\n') == 1
    assert source_lines('value = """first\nsecond\nthird"""\n') == 3


def test_counter_includes_new_core_files_and_walkthrough_loaders(tmp_path):
    for directory in ("nuzlocke", "apps", "tools", "tests"):
        root = tmp_path / directory
        root.mkdir()
        (root / "example.py").write_text("value = 1\n")
    (tmp_path / "nuzlocke" / "walkthrough.py").write_text("def compose():\n    return []\n")
    assert sum(counts(tmp_path).values()) == 4
