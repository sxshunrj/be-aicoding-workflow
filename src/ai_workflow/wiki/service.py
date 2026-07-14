from dataclasses import dataclass

from ai_workflow.errors import AppError
from ai_workflow.wiki.repository import DIRECTORY, WikiRepository


@dataclass(frozen=True, slots=True)
class LintReport:
    valid: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "issues": list(self.issues)}


class WikiService:
    def __init__(self, repository: WikiRepository) -> None:
        self.repository = repository

    def lint(self) -> LintReport:
        issues: list[str] = []
        entries = []
        try:
            self.repository.taxonomy()
            paths = self.repository.paths()
        except AppError as error:
            return LintReport(False, (f"taxonomy/layout: {error.message}",))
        for path in paths:
            try:
                entry = self.repository.read(path)
            except AppError as error:
                issues.append(f"{path.relative_to(self.repository.root)}: {error.message}")
                continue
            entries.append((path, entry))
            if path.parent.name != DIRECTORY[entry.status]:
                issues.append(
                    f"{path.relative_to(self.repository.root)}: directory does not match status {entry.status.value}"
                )
        counts: dict[str, int] = {}
        for _, entry in entries:
            counts[entry.id] = counts.get(entry.id, 0) + 1
        for path, entry in entries:
            relative = path.relative_to(self.repository.root)
            if counts[entry.id] > 1:
                issues.append(f"{relative}: duplicate knowledge id {entry.id}")
            for relation, references in (
                ("supersedes", entry.supersedes),
                ("conflicts_with", entry.conflicts_with),
            ):
                for reference in references:
                    if reference == entry.id:
                        issues.append(f"{relative}: {relation} must not reference itself: {reference}")
                    elif reference not in counts:
                        issues.append(f"{relative}: referenced knowledge id does not exist: {reference}")
        ordered = tuple(sorted(set(issues)))
        return LintReport(not ordered, ordered)
