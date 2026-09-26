from contextrail.canonical import idempotency_key
from contextrail.connectors.fixture import FixtureEntitlements, FixtureGitHub
from contextrail.connectors.state import FixtureState
from contextrail.models import Action
from contextrail.reset import main, reset_all


async def test_reset_undoes_a_demo_run_and_reports_it(tmp_path):
    first = reset_all(tmp_path)
    assert all(r["created"] for r in first.values())

    ents = FixtureEntitlements(FixtureState("entitlements", directory=tmp_path))
    gh = FixtureGitHub(FixtureState("github", directory=tmp_path))
    a = Action.create("A1", "grant", {"entitlement": "jira-pay", "subject_id": "E-1042"})
    b = Action.create("A2", "grant", {"repo": "northbeam/payments-api", "permission": "read", "subject_id": "E-1042"})
    await ents.write(a, idempotency_key("r", a.id, a.params_hash))
    await gh.write(b, idempotency_key("r", b.id, b.params_hash))
    assert (await ents.verify(a))[0] and (await gh.verify(b))[0]

    report = reset_all(tmp_path)
    assert report["entitlements"] == {"changes_undone": 1, "writes_forgotten": 1, "created": False}
    assert report["github"]["changes_undone"] == 1 and report["hris"]["changes_undone"] == 0
    assert not (await ents.verify(a))[0] and not (await gh.verify(b))[0]


def test_cli_prints_every_connector(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    assert main(["reset"]) == 0
    out = capsys.readouterr().out
    for name in ("hris", "entitlements", "github", "slack_corpus"):
        assert name in out
    assert out.count("FIXTURE") == 4
