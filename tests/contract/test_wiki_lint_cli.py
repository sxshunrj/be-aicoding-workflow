import json

from ai_workflow.cli import main


def test_wiki_lint_reports_all_issues_and_nonzero_status(tmp_path, capsys) -> None:
    (tmp_path / "approved").mkdir()
    (tmp_path / "candidates").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "taxonomy.yaml").write_text("schema_version: 1\ntypes: [rule]\nphases: [implement]\n")
    (tmp_path / "approved" / "bad.md").write_text("not front matter", encoding="utf-8")
    (tmp_path / "candidates" / "also-bad.md").write_text("---\nid: nope\n---\n", encoding="utf-8")
    status = main(["wiki", "lint", "--wiki", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert status != 0
    assert payload["ok"] is True
    assert payload["data"]["valid"] is False
    assert len(payload["data"]["issues"]) == 2
    assert payload["data"]["issues"] == sorted(payload["data"]["issues"])


def test_wiki_lint_accepts_empty_lifecycle_directories(tmp_path, capsys) -> None:
    for name in ("approved", "candidates", "archive"):
        (tmp_path / name).mkdir()
    (tmp_path / "taxonomy.yaml").write_text("schema_version: 1\ntypes: [rule]\nphases: [implement]\n")
    status = main(["wiki", "lint", "--wiki", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload == {"ok": True, "data": {"valid": True, "issues": []}}


def test_missing_or_malformed_taxonomy_is_a_lint_issue(tmp_path, capsys) -> None:
    for name in ("approved", "candidates", "archive"):
        (tmp_path / name).mkdir()
    status = main(["wiki", "lint", "--wiki", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert status != 0 and payload["data"]["valid"] is False
    assert "taxonomy" in payload["data"]["issues"][0]


def test_duplicate_taxonomy_values_are_invalid(tmp_path, capsys) -> None:
    for name in ("approved", "candidates", "archive"):
        (tmp_path / name).mkdir()
    (tmp_path / "taxonomy.yaml").write_text(
        "schema_version: 1\ntypes: [rule, rule]\nphases: [implement]\n"
    )
    status = main(["wiki", "lint", "--wiki", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert "unique" in payload["data"]["issues"][0]
