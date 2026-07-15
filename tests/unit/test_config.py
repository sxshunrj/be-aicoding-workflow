from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError


def test_loads_language_neutral_repository_config(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        """
schema_version: 1
repository: demo
services: [payments]
wiki_path: ../team-wiki
commands:
  build: [python, -m, compileall, src]
  unit_test: [pytest, -q]
max_attempts: 3
review_mode: human
knowledge:
  max_entries: 8
  max_characters: 12000
protected_paths: [.git/**, .ai-workflow/**]
disabled_nodes: [verify.integration_test]
""".strip(),
        encoding="utf-8",
    )

    config = RepositoryConfig.load(tmp_path)

    assert config.repository == "demo"
    assert config.command("unit_test") == ("pytest", "-q")
    assert config.command("integration_test") is None
    assert config.wiki_path == (tmp_path / "../team-wiki").resolve()
    assert config.services == ("payments",)
    assert config.protected_paths == (".git/**", ".ai-workflow/**")
    assert config.disabled_nodes == ("verify.integration_test",)


def test_rejects_shell_string_commands(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "schema_version: 1\nrepository: demo\ncommands:\n  test: pytest -q\n",
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="commands.test must be a list"):
        RepositoryConfig.load(tmp_path)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("repository: [", "configuration YAML is invalid"),
        ("- repository\n- demo\n", "configuration must be a mapping"),
        ("repository: demo\ncommands: []\n", "commands must be a mapping"),
        ("repository: demo\nknowledge: []\n", "knowledge must be a mapping"),
        ("commands: {}\n", "repository is required"),
        ("repository: demo\nmax_attempts: many\n", "max_attempts must be an integer"),
        (
            "repository: demo\nknowledge:\n  max_entries: many\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "repository: demo\nreview_mode: unsafe\n",
            "review_mode must be human or auto_accept",
        ),
        ("repository: demo\nmax_attempts: 0\n", "max_attempts must be at least 1"),
        (
            "repository: demo\nknowledge:\n  max_entries: 0\n",
            "knowledge.max_entries must be positive",
        ),
        (
            "repository: demo\nknowledge:\n  max_characters: 0\n",
            "knowledge.max_characters must be positive",
        ),
        (
            "repository: demo\nservices: payments\n",
            "services must be a list of strings",
        ),
        (
            "repository: demo\nprotected_paths: [.git/**, 3]\n",
            "protected_paths must be a list of strings",
        ),
        (
            "repository: demo\ndisabled_nodes: [verify.build, false]\n",
            "disabled_nodes must be a list of strings",
        ),
    ],
)
def test_rejects_invalid_configuration_shapes(
    tmp_path: Path, contents: str, message: str
) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(contents, encoding="utf-8")

    with pytest.raises(AppError, match=message) as error:
        RepositoryConfig.load(tmp_path)

    assert error.value.code == "config_invalid"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("repository: demo\nmax_attempts: true\n", "max_attempts must be an integer"),
        ("repository: demo\nmax_attempts: 1.5\n", "max_attempts must be an integer"),
        (
            "repository: demo\nknowledge:\n  max_entries: true\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "repository: demo\nknowledge:\n  max_entries: 1.5\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "repository: demo\nknowledge:\n  max_characters: true\n",
            "knowledge.max_characters must be an integer",
        ),
        (
            "repository: demo\nknowledge:\n  max_characters: 1.5\n",
            "knowledge.max_characters must be an integer",
        ),
    ],
)
def test_rejects_coercible_non_integer_limits(
    tmp_path: Path, contents: str, message: str
) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(contents, encoding="utf-8")

    with pytest.raises(AppError, match=message) as error:
        RepositoryConfig.load(tmp_path)

    assert error.value.code == "config_invalid"
