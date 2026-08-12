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


def test_loads_repository_adapter_fields_for_integration_generation(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        """
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
        (
            "repository: demo\nadapter: []\n",
            "adapter must be a mapping",
        ),
        (
            "repository: demo\nadapter:\n  source_paths: src/**\n",
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


def test_load_wecom_block_and_defaults(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n"
        "  notify_tag: 工作流通知组\n"
        "  creator_userid_env: WECOM_CREATOR_USERID\n",
        encoding="utf-8",
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_enabled is True
    assert config.wecom_corpid_env == "WECOM_CORPID"
    assert config.wecom_agentid_env == "WECOM_AGENT_ID"
    assert config.wecom_agent_secret_env == "WECOM_AGENT_SECRET"
    assert config.wecom_notify_tag == "工作流通知组"
    assert config.wecom_creator_userid_env == "WECOM_CREATOR_USERID"
    assert config.wecom_gates == ("review", "blocked", "governance", "git_handoff")


def test_load_wecom_disabled_by_default(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_enabled is False
    assert config.wecom_notify_tag is None
    assert config.wecom_gates == ("review", "blocked", "governance", "git_handoff")


def test_load_wecom_gates_restricts_choices(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review, blocked]\n",
        encoding="utf-8",
    )
    config = RepositoryConfig.load(tmp_path)
    assert config.wecom_gates == ("review", "blocked")


def test_load_wecom_rejects_unknown_gate(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review, nonsense]\n",
        encoding="utf-8",
    )
    with pytest.raises(AppError) as exc:
        RepositoryConfig.load(tmp_path)
    assert exc.value.code == "config_invalid"
