from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.path_authorization import RepositoryPathAuthorizer


def _config(
    repo: Path,
    *,
    protected_paths: tuple[str, ...] = (),
    adapter: str = "",
) -> RepositoryConfig:
    protected = ""
    if protected_paths:
        protected = (
            "protected_paths:\n"
            + "".join(f"  - {path}\n" for path in protected_paths)
        )
    (repo / ".ai-workflow.yaml").write_text(
        f"repository: demo\n{protected}{adapter}",
        encoding="utf-8",
    )
    return RepositoryConfig.load(repo)


@pytest.fixture
def authorizer(tmp_path: Path) -> RepositoryPathAuthorizer:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return RepositoryPathAuthorizer(
        tmp_path,
        _config(
            tmp_path,
            protected_paths=(".git/**", ".ai-workflow/**"),
            adapter=(
                "adapter:\n"
                "  source_paths: [src/**]\n"
                "  test_paths: [tests/**]\n"
                "  generated_test_destinations: [tests/generated]\n"
                "  report_paths: [reports/integration.json]\n"
            ),
        ),
    )


@pytest.mark.parametrize(
    "path",
    ["", ".", "../secret", "/tmp/secret", "src//app.py", "src\\app.py"],
)
def test_authorize_rejects_noncanonical_paths(
    authorizer: RepositoryPathAuthorizer, path: str
) -> None:
    with pytest.raises(AppError) as error:
        authorizer.authorize("input", path)

    assert error.value.code == "path_not_authorized"


@pytest.mark.parametrize("path", [".git", ".git/config", ".ai-workflow/state.yaml"])
def test_git_and_workflow_paths_are_always_denied(
    authorizer: RepositoryPathAuthorizer, path: str
) -> None:
    with pytest.raises(AppError) as error:
        authorizer.authorize("input", path)

    assert error.value.code == "path_not_authorized"


def test_literal_protected_path_denies_descendants(tmp_path: Path) -> None:
    (tmp_path / "src" / "private").mkdir(parents=True)
    config = _config(
        tmp_path,
        protected_paths=("src/private",),
        adapter="adapter:\n  source_paths: [src/**]\n",
    )
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    with pytest.raises(AppError) as error:
        authorizer.authorize("input", "src/private/secrets.py")

    assert error.value.code == "path_not_authorized"


def test_protected_deny_beats_adapter_and_helper_owned_allow(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "integration.json").write_text("{}", encoding="utf-8")
    config = _config(
        tmp_path,
        protected_paths=("reports/**",),
        adapter="adapter:\n  report_paths: [reports/integration.json]\n",
    )
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    with pytest.raises(AppError) as adapter_error:
        authorizer.authorize("report", "reports/integration.json")
    with pytest.raises(AppError) as helper_error:
        authorizer.authorize(
            "report",
            "reports/integration.json",
            helper_owned_report_paths=("reports/integration.json",),
        )

    assert adapter_error.value.code == "path_not_authorized"
    assert helper_error.value.code == "path_not_authorized"


def test_escaping_symlink_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "src").symlink_to(outside, target_is_directory=True)
    config = _config(tmp_path, adapter="adapter:\n  source_paths: [src/**]\n")
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    with pytest.raises(AppError) as error:
        authorizer.authorize("input", "src/escape.py")

    assert error.value.code == "path_not_authorized"


def test_generated_test_and_report_are_limited_to_their_destinations(
    authorizer: RepositoryPathAuthorizer,
) -> None:
    assert (
        authorizer.authorize("generated-test", "tests/generated/new_case.json")
        == "tests/generated/new_case.json"
    )
    assert (
        authorizer.authorize("report", "reports/integration.json")
        == "reports/integration.json"
    )

    with pytest.raises(AppError):
        authorizer.authorize("generated-test", "tests/manual/new_case.json")
    with pytest.raises(AppError):
        authorizer.authorize("report", "reports/other.json")


def test_adapter_source_and_test_paths_form_input_union(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    config = _config(
        tmp_path,
        adapter=(
            "adapter:\n"
            "  source_paths: [src/**]\n"
            "  test_paths: [tests/**]\n"
        ),
    )
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    assert authorizer.authorize("input", "src/app.py") == "src/app.py"
    assert authorizer.authorize("input", "tests/test_app.py") == "tests/test_app.py"
    with pytest.raises(AppError):
        authorizer.authorize("input", "docs/spec.md")


def test_adapter_glob_does_not_authorize_sibling_prefix(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src-private").mkdir()
    config = _config(tmp_path, adapter="adapter:\n  source_paths: [src/**]\n")
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    with pytest.raises(AppError) as error:
        authorizer.authorize("input", "src-private/secrets.py")

    assert error.value.code == "path_not_authorized"


def test_fallback_inputs_descend_around_protected_children(tmp_path: Path) -> None:
    (tmp_path / "src" / "public").mkdir(parents=True)
    (tmp_path / "src" / "private").mkdir()
    (tmp_path / "docs").mkdir()
    config = _config(tmp_path, protected_paths=("src/private",))
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    assert authorizer.allowed_input_paths() == ("docs", "src/public")


def test_helper_owned_input_still_obeys_protected_paths(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    config = _config(tmp_path, protected_paths=("artifacts/**",))
    authorizer = RepositoryPathAuthorizer(tmp_path, config)

    with pytest.raises(AppError) as error:
        authorizer.allowed_input_paths(
            helper_owned_input_paths=("artifacts/spec-spec.md",)
        )

    assert error.value.code == "path_not_authorized"


def test_checkpoint_scope_rejects_reports_symlinks_and_special_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "reports" / "integration.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src" / "link.py").symlink_to(tmp_path / "src" / "app.py")
    config = _config(
        tmp_path,
        adapter="adapter:\n  report_paths: [reports/integration.json]\n",
    )
    scope = RepositoryPathAuthorizer(tmp_path, config).checkpoint_scope()

    assert scope.authorize("src/app.py") == "src/app.py"
    for path in ("reports/integration.json", "src/link.py"):
        with pytest.raises(AppError) as error:
            scope.authorize(path)
        assert error.value.code == "path_not_authorized"


def test_checkpoint_scope_rejects_directories_with_denied_descendants(
    tmp_path: Path,
) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "integration.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src" / "private").mkdir(parents=True)
    (tmp_path / "src" / "private" / "secret.py").write_text("", encoding="utf-8")
    config = _config(
        tmp_path,
        protected_paths=("src/private",),
        adapter="adapter:\n  report_paths: [reports/integration.json]\n",
    )
    scope = RepositoryPathAuthorizer(tmp_path, config).checkpoint_scope()

    for path in ("reports", "src"):
        with pytest.raises(AppError) as error:
            scope.authorize(path)
        assert error.value.code == "path_not_authorized"
