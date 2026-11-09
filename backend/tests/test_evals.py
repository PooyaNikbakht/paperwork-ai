import json

from app.evals import main, same_value


def test_same_value():
    assert same_value("money", 1014.14, 1014.144)
    assert not same_value("money", 1280.0, 1230.0)
    assert same_value("text", "Northpeak Office Supply Ltd.", "northpeak office supply ltd")
    assert same_value("text", None, None)
    assert not same_value("text", None, "something")


def test_mock_eval_report(tmp_path, capsys):
    out = tmp_path / "evals.json"
    assert main(["--provider=mock", f"--json={out}"]) == 0
    summary = json.loads(out.read_text())["summary"]
    assert summary["documents"] == 12 and summary["errors"] == 0
    assert summary["document_problems_caught"] == [4, 4]
    assert summary["extraction_mistakes_caught"] == [1, 1]
    assert summary["false_alarms_on_clean_documents"][0] == 0
    assert "Field accuracy" in capsys.readouterr().out


def test_live_providers_need_keys(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir("/")  # no .env file
    assert main(["--provider=anthropic"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
