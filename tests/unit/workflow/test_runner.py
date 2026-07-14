import sys

from ai_workflow.workflow.runner import CommandRunner


def test_command_runner_uses_argv_without_shell_and_bounds_output(tmp_path) -> None:
    evidence = CommandRunner(max_output_characters=20).run(
        (sys.executable, "-c", "print('x' * 100)"), tmp_path, 5
    )

    assert evidence.argv[0] == sys.executable
    assert evidence.exit_status == 0
    assert len(evidence.output) == 20
    assert evidence.output_truncated is True
