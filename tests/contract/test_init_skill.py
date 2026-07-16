from pathlib import Path

from ai_workflow.cli import main


SKILL_DIR = Path("skills/ai-workflow-init")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_init_skill_frontmatter_and_strict_sequence() -> None:
    skill = _read()

    assert skill.startswith(
        "---\nname: ai-workflow-init\n"
        "description: Use when installing or diagnosing the ai-workflow Wave 1 Skill suite for Codex or Claude Code.\n"
        "---\n"
    )
    assert (
        "locate/update ai-workflow-init -> reread the latest SKILL.md -> run the latest scripts/init.sh "
        "-> inspect installed/updated/skipped/failed summary -> run doctor"
    ) in skill
    assert "Do not let scripts/init.sh update this Skill by itself" in skill
    assert "installed/updated/skipped/failed" in skill


def test_init_skill_scripts_delegate_without_shell_interpolation() -> None:
    init_sh = _read("scripts/init.sh")
    install_py = _read("scripts/install.py")

    assert 'python3 "$SCRIPT_DIR/install.py" "$@"' in init_sh
    assert "subprocess.run(argv, shell=False" in install_py
    assert "source_root = skill_dir.parents[1]" in install_py
    assert "ai-workflow" in install_py


def test_init_skill_has_ui_metadata() -> None:
    metadata = _read("agents/openai.yaml")

    assert "display_name" in metadata
    assert "$ai-workflow-init" in metadata


def test_install_and_doctor_cli_commands_exist(capsys) -> None:
    install_status = main(["install"])
    install_payload = capsys.readouterr().out
    doctor_status = main(["doctor"])
    doctor_payload = capsys.readouterr().out

    assert install_status != 0
    assert doctor_status != 0
    assert "invalid_arguments" in install_payload
    assert "invalid_arguments" in doctor_payload
