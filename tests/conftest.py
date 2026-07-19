from pathlib import Path
import subprocess
import sys

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "src"))


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def git(self, *args: str, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @property
    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def rev_parse(self, revision: str) -> str:
        return self.git("rev-parse", revision)

    def snapshot_git_state(self) -> dict[str, object]:
        head = self.git("rev-parse", "HEAD")
        symbolic = self.git("symbolic-ref", "-q", "HEAD")
        branch_ref = self.git("rev-parse", symbolic)
        index = (self.root / ".git" / "index").read_bytes()
        return {
            "head": head,
            "symbolic": symbolic,
            "branch_ref": branch_ref,
            "index": index,
        }


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    repo = GitRepo(tmp_path)
    repo.git("init")
    repo.git("config", "user.name", "Test User")
    repo.git("config", "user.email", "test@example.com")
    repo.write(
        ".ai-workflow.yaml",
        "repository: checkpoint-test\nprotected_paths: [.git/**, .ai-workflow/**]\n",
    )
    repo.write("src/app.py", "original\n")
    repo.git("add", ".ai-workflow.yaml", "src/app.py")
    repo.git("commit", "-m", "initial")
    return repo
