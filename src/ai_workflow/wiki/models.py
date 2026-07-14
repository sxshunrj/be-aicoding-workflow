from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from typing import Mapping
from ai_workflow.errors import AppError

class KnowledgeStatus(StrEnum):
    CANDIDATE="candidate"; APPROVED="approved"; ARCHIVED="archived"; SUPERSEDED="superseded"
class KnowledgeType(StrEnum):
    RULE="rule"; DECISION="decision"; PATTERN="pattern"; PITFALL="pitfall"; PROCEDURE="procedure"
@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    repos: tuple[str,...]=(); services: tuple[str,...]=(); paths: tuple[str,...]=(); languages: tuple[str,...]=(); phases: tuple[str,...]=()
@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    id:str; title:str; type:KnowledgeType; status:KnowledgeStatus; summary:str; scope:KnowledgeScope
    tags:tuple[str,...]; owners:tuple[str,...]; reviewers:tuple[str,...]; created_at:date
    reviewed_at:date|None; review_after:date; sources:tuple[dict[str,str],...]
    supersedes:tuple[str,...]; conflicts_with:tuple[str,...]; body:str
    @classmethod
    def from_parts(cls, metadata:Mapping[str,object], body:str)->"KnowledgeEntry":
        def text(name:str)->str:
            value=metadata.get(name)
            if not isinstance(value,str) or not value.strip(): raise AppError("wiki_invalid",f"{name} must not be empty")
            return value.strip()
        def strings(value:object,name:str,required:bool=False)->tuple[str,...]:
            if not isinstance(value,list) or not all(isinstance(x,str) and x.strip() for x in value): raise AppError("wiki_invalid",f"{name} must be a list of non-empty strings")
            result=tuple(x.strip() for x in value)
            if required and not result: raise AppError("wiki_invalid",f"{name} must not be empty")
            return result
        entry_id=text("id")
        if not re.fullmatch(r"KW-[a-z0-9-]+-[0-9]{3,}",entry_id): raise AppError("wiki_invalid","knowledge id is invalid")
        try: kind,status=KnowledgeType(text("type")),KnowledgeStatus(text("status"))
        except ValueError as error: raise AppError("wiki_invalid","unknown knowledge type or status") from error
        raw_scope=metadata.get("scope")
        if not isinstance(raw_scope,dict): raise AppError("wiki_invalid","scope must be a mapping")
        scope=KnowledgeScope(**{n:strings(raw_scope.get(n,[]),f"scope.{n}") for n in ("repos","services","paths","languages","phases")})
        if set(scope.phases)-{"spec","plan","implement","verify"}: raise AppError("wiki_invalid","scope contains an unknown phase")
        created_at=_date(metadata.get("created_at"),"created_at"); reviewed_at=_date(metadata.get("reviewed_at"),"reviewed_at",True); review_after=_date(metadata.get("review_after"),"review_after")
        assert created_at is not None and review_after is not None
        if reviewed_at and review_after<reviewed_at: raise AppError("wiki_invalid","review_after must not precede reviewed_at")
        reviewers=strings(metadata.get("reviewers"),"reviewers")
        if status is KnowledgeStatus.APPROVED and not reviewers: raise AppError("wiki_invalid","approved knowledge requires a reviewer")
        if status is KnowledgeStatus.APPROVED and reviewed_at is None: raise AppError("wiki_invalid","approved knowledge requires reviewed_at")
        raw_sources=metadata.get("sources")
        if not isinstance(raw_sources,list): raise AppError("wiki_invalid","sources must be a list")
        sources=[]
        for source in raw_sources:
            if not isinstance(source,dict) or source.get("kind") not in {"run","human"} or not isinstance(source.get("ref"),str) or not source["ref"].strip(): raise AppError("wiki_invalid","source must have a run or human kind and ref")
            sources.append({"kind":str(source["kind"]),"ref":source["ref"].strip()})
        if not sources: raise AppError("wiki_invalid","candidate knowledge requires a source" if status is KnowledgeStatus.CANDIDATE else "sources must not be empty")
        if not body.strip(): raise AppError("wiki_invalid","Markdown body must not be empty")
        return cls(entry_id,text("title"),kind,status,text("summary"),scope,strings(metadata.get("tags"),"tags"),strings(metadata.get("owners"),"owners",True),reviewers,created_at,reviewed_at,review_after,tuple(sources),strings(metadata.get("supersedes"),"supersedes"),strings(metadata.get("conflicts_with"),"conflicts_with"),body.strip())
def _date(value:object,name:str,optional:bool=False)->date|None:
    if value is None and optional:return None
    if isinstance(value,date):return value
    if isinstance(value,str):
        try:return date.fromisoformat(value)
        except ValueError:pass
    raise AppError("wiki_invalid",f"{name} must be an ISO date")
