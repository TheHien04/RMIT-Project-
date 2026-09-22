from pathlib import Path

import pytest

from coach.llm import maybe_llm
from coach.privacy import EgressLog
from coach.settings import load_settings
from coach.speaker import EdgeSpeaker, LocalSpeaker


def test_env_file_keeps_cloud_features_off_without_a_key(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "COACH_LLM", "COACH_VISION", "COACH_TTS", "COACH_MIC"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "OPENAI_API_KEY=\nCOACH_LLM=true\nCOACH_VISION=false\nCOACH_TTS=print\n",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.llm_enabled is True
    assert settings.vision_enabled is False
    assert settings.tts == "print"
    assert maybe_llm(settings) is None


def test_process_environment_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COACH_HEADED", "false")
    path = tmp_path / ".env"
    path.write_text("COACH_HEADED=true\n", encoding="utf-8")
    assert load_settings(path).headed is False


def test_real_web_paths_are_resolved_under_coach_root(tmp_path, monkeypatch):
    for name in ("COACH_CDP_URL", "COACH_LESSON_PDF", "COACH_TARGET_MANIFEST"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "COACH_CDP_URL=http://127.0.0.1:9222\n"
        "COACH_ALLOWED_ORIGINS=https://demo.supabase.co\n"
        "COACH_LESSON_PDF=fixtures/real.pdf\n"
        "COACH_TARGET_MANIFEST=fixtures/flow.json\n",
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.cdp_url == "http://127.0.0.1:9222"
    assert settings.allowed_origins == ("https://demo.supabase.co",)
    assert settings.lesson_pdf.name == "real.pdf"
    assert settings.target_manifest.name == "flow.json"


def test_edge_speech_is_recorded_as_leaving(monkeypatch):
    async def fake_save(text, voice, path):
        Path(path).write_bytes(b"mp3")

    monkeypatch.setattr("coach.speaker._save_edge", fake_save)
    monkeypatch.setattr("coach.speaker.shutil.which", lambda name: None)
    log = EgressLog()
    speaker = EdgeSpeaker("vi-VN-HoaiMyNeural")
    speaker.say("qua phải", log)
    assert log.events[0].left_machine is True
    assert log.events[0].summary["chars"] == len("qua phải")
    speaker.say("qua phải", log)
    assert log.events[1].left_machine is False
    assert log.events[1].summary["provider"] == "edge-cache"


def test_local_tts_stays_on_the_machine():
    log = EgressLog()
    LocalSpeaker().say("tới rồi", log)
    assert log.events[0].left_machine is False


def test_unknown_tts_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("COACH_TTS", raising=False)
    path = tmp_path / ".env"
    path.write_text("COACH_TTS=cloud\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path)
