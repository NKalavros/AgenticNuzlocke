from nuzlocke.llm.json_util import extract_json_object


def test_extract_json_fenced():
    text = 'Sure.\n```json\n{"a": 1, "b": "x"}\n```\n'
    assert extract_json_object(text) == {"a": 1, "b": "x"}


def test_extract_json_raw():
    assert extract_json_object('prefix {"actions": ["walk_up"]} suffix') == {"actions": ["walk_up"]}
