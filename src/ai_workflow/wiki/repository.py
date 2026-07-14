from dataclasses import fields
from pathlib import Path
import yaml
from ai_workflow.errors import AppError
from ai_workflow.wiki.models import KnowledgeEntry,KnowledgeScope,KnowledgeStatus
DIRECTORY={KnowledgeStatus.CANDIDATE:"candidates",KnowledgeStatus.APPROVED:"approved",KnowledgeStatus.ARCHIVED:"archive",KnowledgeStatus.SUPERSEDED:"archive"}
class WikiRepository:
    def __init__(self,root:Path):self.root=Path(root)
    def paths(self):return sorted(p for name in ("approved","candidates","archive") for p in (self.root/name).glob("*.md"))
    def list(self,status):
        wanted=KnowledgeStatus(status)
        return sorted((e for p in self.paths() if p.parent.name==DIRECTORY[wanted] for e in [self.read(p)] if e.status is wanted),key=lambda e:e.id)
    def read(self,path):
        try:content=Path(path).read_text(encoding="utf-8")
        except OSError as error:raise AppError("wiki_invalid",f"cannot read {path}: {error}") from error
        if not content.startswith("---\n"):raise AppError("wiki_invalid","Markdown file must begin with YAML front matter")
        parts=content.split("---\n",2)
        if len(parts)!=3:raise AppError("wiki_invalid","Markdown file is missing the closing front matter delimiter")
        try:loaded=yaml.safe_load(parts[1])
        except yaml.YAMLError as error:raise AppError("wiki_invalid","front matter YAML is invalid") from error
        if not isinstance(loaded,dict):raise AppError("wiki_invalid","front matter must be a mapping")
        return KnowledgeEntry.from_parts(loaded,parts[2])
    def write_candidate(self,entry):
        if entry.status is not KnowledgeStatus.CANDIDATE:raise AppError("wiki_invalid","only candidate knowledge can be written")
        directory=self.root/"candidates";directory.mkdir(parents=True,exist_ok=True);path=directory/f"{entry.id}.md";path.write_text(_serialize(entry),encoding="utf-8");return path
    def move(self,entry_id,source,target):
        source_path=self.root/DIRECTORY[KnowledgeStatus(source)]/f"{entry_id}.md"
        if not source_path.is_file():raise AppError("wiki_not_found",f"knowledge entry not found: {entry_id}")
        directory=self.root/DIRECTORY[KnowledgeStatus(target)];directory.mkdir(parents=True,exist_ok=True);target_path=directory/source_path.name;source_path.replace(target_path);return target_path
def _serialize(entry):
    metadata={f.name:getattr(entry,f.name) for f in fields(entry) if f.name!="body"};metadata["type"]=entry.type.value;metadata["status"]=entry.status.value;metadata["scope"]={f.name:list(getattr(entry.scope,f.name)) for f in fields(KnowledgeScope)}
    for n in ("tags","owners","reviewers","sources","supersedes","conflicts_with"):metadata[n]=list(metadata[n])
    return f"---\n{yaml.safe_dump(metadata,sort_keys=False)}---\n{entry.body}\n"
