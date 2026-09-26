import pytest

from contextrail.policy.loader import RULES_DIR, RuleLoadError, load_rules

GOOD = """
id: POL-TST-001
title: Test rule
source: {okf: knowledge/policies/test.md, clause: "§1"}
clause_text: "A test clause long enough to be quoted verbatim."
match: {kind: grant}
verdict: ALLOW
"""


def write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_loads_valid_rules_sorted(tmp_path):
    write(tmp_path, "pol-tst-001.yaml", GOOD)
    write(tmp_path, "pol-tst-000.yaml", GOOD.replace("POL-TST-001", "POL-TST-000"))
    assert [r.id for r in load_rules(tmp_path)] == ["POL-TST-000", "POL-TST-001"]


def test_reports_every_problem_at_once(tmp_path):
    write(tmp_path, "pol-tst-001.yaml", GOOD)
    write(tmp_path, "pol-tst-002.yaml", GOOD.replace("POL-TST-001", "POL-TST-002") + "conditions: ['evidence.x == 1']\n")
    write(tmp_path, "broken.yaml", "id: [unclosed")
    write(tmp_path, "wrong-name.yaml", GOOD.replace("POL-TST-001", "POL-TST-003"))
    write(tmp_path, "list.yaml", "- a\n- b\n")
    with pytest.raises(RuleLoadError) as e:
        load_rules(tmp_path)
    text = "\n".join(e.value.problems)
    assert "pol-tst-002.yaml" in text and "P6" in text
    assert "broken.yaml: YAML error" in text
    assert "wrong-name.yaml: file must be named pol-tst-003.yaml" in text
    assert "list.yaml: expected one rule" in text
    assert len(e.value.problems) == 4


def test_duplicate_ids_rejected(tmp_path):
    write(tmp_path, "pol-tst-001.yaml", GOOD)
    write(tmp_path, "pol-tst-009.yaml", GOOD)  # a second file declaring POL-TST-001
    with pytest.raises(RuleLoadError, match="duplicate rule id POL-TST-001"):
        load_rules(tmp_path)


def test_yaml_tags_cannot_construct_objects(tmp_path):
    write(tmp_path, "pol-tst-001.yaml", "!!python/object/apply:os.system ['echo pwned']\n")
    with pytest.raises(RuleLoadError, match="YAML error"):
        load_rules(tmp_path)


def test_shipped_rules_directory_loads():
    assert RULES_DIR.is_dir()
    load_rules()  # the engine's own rules must always load


def test_engine_refuses_to_start_with_bad_rules(tmp_path, monkeypatch):
    from contextrail import main
    from contextrail.settings import Settings

    write(tmp_path, "pol-tst-001.yaml", GOOD + "conditions: ['evidence.x == 1']" + chr(10))
    monkeypatch.setattr(main, "load_rules", lambda: load_rules(tmp_path))
    with pytest.raises(RuleLoadError):
        main.create_app(Settings(_env_file=None))
