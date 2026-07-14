from dataclasses import dataclass
from ai_workflow.errors import AppError
from ai_workflow.wiki.repository import DIRECTORY,WikiRepository
@dataclass(frozen=True,slots=True)
class LintReport:
    valid:bool;issues:tuple[str,...]
    def to_dict(self):return {"valid":self.valid,"issues":list(self.issues)}
class WikiService:
    def __init__(self,repository:WikiRepository):self.repository=repository
    def lint(self):
        issues=[];entries=[]
        for path in self.repository.paths():
            try:entry=self.repository.read(path)
            except AppError as error:issues.append(f"{path.relative_to(self.repository.root)}: {error.message}");continue
            entries.append((path,entry))
            if path.parent.name!=DIRECTORY[entry.status]:issues.append(f"{path.relative_to(self.repository.root)}: directory does not match status {entry.status.value}")
        counts={}
        for _,entry in entries:counts[entry.id]=counts.get(entry.id,0)+1
        for path,entry in entries:
            if counts[entry.id]>1:issues.append(f"{path.relative_to(self.repository.root)}: duplicate knowledge id {entry.id}")
            for ref in (*entry.supersedes,*entry.conflicts_with):
                if ref not in counts:issues.append(f"{path.relative_to(self.repository.root)}: referenced knowledge id does not exist: {ref}")
        ordered=tuple(sorted(set(issues)));return LintReport(not ordered,ordered)
