from pathlib import Path


def test_openai_skill_list_display_names_are_english() -> None:
    for path in sorted(Path("skills").glob("*/agents/openai.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "display_name:" in text
        assert "short_description:" in text
        assert "default_prompt:" in text
        display_line = next(line for line in text.splitlines() if "display_name:" in line)
        assert display_line.isascii(), f"{path} display_name should stay English"
