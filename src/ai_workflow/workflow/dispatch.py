import json
from pathlib import Path

from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError


OWNER_CONTRACT = {
    "spec.spec": "spec-writer.md",
    "plan.solution": "planner.md",
    "plan.test_strategy": "planner.md",
    "implement.code": "coder.md",
    "verify.build": "test-runner.md",
    "verify.unit_test": "test-runner.md",
    "verify.integration_test": "test-runner.md",
    "verify.code_review": "code-reviewer.md",
}


def render_prompt_file(packet: DispatchPacket, path: Path) -> Path:
    payload = json.dumps(
        packet.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
    )
    content = (
        "# Child Dispatch Prompt\n\n"
        "Follow the owner and common contracts referenced by the dispatch packet.\n\n"
        "## Rules\n\n"
        "- Read only the allowed inputs.\n"
        "- Write only the assigned artifact.\n"
        "- Do not edit workflow state.\n"
        "- Do not read raw Wiki Markdown.\n"
        "- Return only schema-v2 ChildResult JSON.\n\n"
        "## Dispatch Packet\n\n"
        f"```json\n{payload}\n```\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as prompt_file:
            prompt_file.write(content)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != content:
            raise AppError(
                "dispatch_prompt_conflict",
                f"dispatch prompt already exists with different content: {path}",
            )
    return path
