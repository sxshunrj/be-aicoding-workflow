from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig, migrate_repository_config
from ai_workflow.errors import AppError


def test_loads_language_neutral_repository_config(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        """
schema_version: 2
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


def test_loads_repository_adapter_fields_for_integration_generation(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        """
schema_version: 2
repository: demo
adapter:
  source_paths: [src/**]
  test_paths: [tests/**]
  generated_test_destinations: [tests/generated]
  report_paths: [reports/integration.json]
""".strip(),
        encoding="utf-8",
    )

    config = RepositoryConfig.load(tmp_path)

    assert config.adapter_source_paths == ("src/**",)
    assert config.adapter_test_paths == ("tests/**",)
    assert config.adapter_generated_test_destinations == ("tests/generated",)
    assert config.adapter_report_paths == ("reports/integration.json",)


def test_rejects_shell_string_commands(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "schema_version: 2\nrepository: demo\ncommands:\n  test: pytest -q\n",
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="commands.test must be a list"):
        RepositoryConfig.load(tmp_path)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("schema_version: 2\nrepository: [", "configuration YAML is invalid"),
        ("- repository\n- demo\n", "configuration must be a mapping"),
        ("schema_version: 2\nrepository: demo\ncommands: []\n", "commands must be a mapping"),
        ("schema_version: 2\nrepository: demo\nknowledge: []\n", "knowledge must be a mapping"),
        ("schema_version: 2\ncommands: {}\n", "repository is required"),
        ("schema_version: 2\nrepository: demo\nmax_attempts: many\n", "max_attempts must be an integer"),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_entries: many\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "schema_version: 2\nrepository: demo\nreview_mode: unsafe\n",
            "review_mode must be human or auto_accept",
        ),
        ("schema_version: 2\nrepository: demo\nmax_attempts: 0\n", "max_attempts must be at least 1"),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_entries: 0\n",
            "knowledge.max_entries must be positive",
        ),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_characters: 0\n",
            "knowledge.max_characters must be positive",
        ),
        (
            "schema_version: 2\nrepository: demo\nservices: payments\n",
            "services must be a list of strings",
        ),
        (
            "schema_version: 2\nrepository: demo\nprotected_paths: [.git/**, 3]\n",
            "protected_paths must be a list of strings",
        ),
        (
            "schema_version: 2\nrepository: demo\ndisabled_nodes: [verify.build, false]\n",
            "disabled_nodes must be a list of strings",
        ),
        (
            "schema_version: 2\nrepository: demo\nadapter: []\n",
            "adapter must be a mapping",
        ),
        (
            "schema_version: 2\nrepository: demo\nadapter:\n  source_paths: src/**\n",
            "adapter.source_paths must be a list of strings",
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
        ("schema_version: 2\nrepository: demo\nmax_attempts: true\n", "max_attempts must be an integer"),
        ("schema_version: 2\nrepository: demo\nmax_attempts: 1.5\n", "max_attempts must be an integer"),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_entries: true\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_entries: 1.5\n",
            "knowledge.max_entries must be an integer",
        ),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_characters: true\n",
            "knowledge.max_characters must be an integer",
        ),
        (
            "schema_version: 2\nrepository: demo\nknowledge:\n  max_characters: 1.5\n",
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


def test_rejects_legacy_schema_version_with_a_migration_hint(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "schema_version: 1\nrepository: demo\n", encoding="utf-8"
    )

    with pytest.raises(AppError) as error:
        RepositoryConfig.load(tmp_path)

    assert error.value.code == "unsupported_schema_version"
    assert "config migrate" in error.value.message


def test_rejects_a_missing_schema_version(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")

    with pytest.raises(AppError) as error:
        RepositoryConfig.load(tmp_path)

    assert error.value.code == "unsupported_schema_version"


def test_migrate_adds_the_version_and_preserves_everything_else(tmp_path: Path) -> None:
    path = tmp_path / ".ai-workflow.yaml"
    path.write_text(
        "# team config\nrepository: demo\ncommands:\n  unit_test: [pytest, -q]\n",
        encoding="utf-8",
    )

    result = migrate_repository_config(tmp_path)

    assert result.changed
    assert result.from_version == 1
    assert result.to_version == 2
    assert result.to_dict()["dry_run"] is False
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# team config\nschema_version: 2\n")
    assert "commands:\n  unit_test: [pytest, -q]\n" in text
    assert RepositoryConfig.load(tmp_path).command("unit_test") == ("pytest", "-q")


def test_migrate_rewrites_an_existing_version_line(tmp_path: Path) -> None:
    path = tmp_path / ".ai-workflow.yaml"
    path.write_text("repository: demo\nschema_version: 1\n", encoding="utf-8")

    result = migrate_repository_config(tmp_path)

    assert result.from_version == 1
    assert path.read_text(encoding="utf-8") == "repository: demo\nschema_version: 2\n"


def test_migrate_is_idempotent_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / ".ai-workflow.yaml"
    path.write_text("schema_version: 1\nrepository: demo\n", encoding="utf-8")

    dry_run = migrate_repository_config(tmp_path, dry_run=True)
    assert dry_run.changed
    assert dry_run.dry_run
    assert path.read_text(encoding="utf-8").startswith("schema_version: 1")

    migrate_repository_config(tmp_path)
    again = migrate_repository_config(tmp_path)
    assert not again.changed
    assert again.from_version == 2


def test_migrate_refuses_an_unknown_version(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "schema_version: 9\nrepository: demo\n", encoding="utf-8"
    )

    with pytest.raises(AppError) as error:
        migrate_repository_config(tmp_path)

    assert error.value.code == "unsupported_schema_version"


def test_migrate_requires_a_configuration_file(tmp_path: Path) -> None:
    with pytest.raises(AppError) as error:
        migrate_repository_config(tmp_path)

    assert error.value.code == "config_not_found"
