from pathlib import Path


def test_openai_skill_list_metadata_is_english_ascii() -> None:
    for path in sorted(Path("skills").glob("*/agents/openai.yaml")):
        text = path.read_text(encoding="utf-8")
        assert text.isascii(), f"{path} should keep UI metadata in English ASCII"
        assert "display_name:" in text
        assert "short_description:" in text
        assert "default_prompt:" in text
