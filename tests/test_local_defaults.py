from pathlib import Path

from delivery.config import Settings


def test_local_settings_do_not_implicitly_load_cloud_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("LLM_PROVIDER", "GOOGLE_CREDENTIALS_JSON", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "LLM_PROVIDER=vertex\nGOOGLE_CREDENTIALS_JSON=should-not-be-loaded\n"
    )
    settings = Settings()
    assert settings.llm_provider == "disabled"
    assert settings.google_credentials_json == ""
