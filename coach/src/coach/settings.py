"""Runtime settings. The process environment overrides the .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    llm_enabled: bool
    vision_enabled: bool
    mic_enabled: bool
    barge_in: bool
    headed: bool
    tts: str
    edge_voice: str
    whisper_model: str
    whisper_language: str
    whisper_device: str
    whisper_compute_type: str
    zerotts_model: str
    zerotts_voice: str
    zerotts_cache_dir: Path
    sandbox_port: int
    cue_poll_seconds: float
    vad_min_volume: float
    egress_log: Path
    browser_audit_log: Path
    cdp_url: str
    allowed_origins: tuple[str, ...]
    target_tab_title: str
    navigation_mode: str
    inject_navigation: bool
    target_manifest: Path | None
    agent_browser_bin: str
    lesson_pdf: Path | None
    env_file: Path


def load_settings(env_file: Path | None = None) -> Settings:
    path = env_file or (ROOT / ".env")
    file_values = _parse_env_file(path) if path.is_file() else {}

    def value(name: str, default: str) -> str:
        if name in os.environ:
            return os.environ[name]
        return file_values.get(name, default)

    tts = value("COACH_TTS", "auto").strip().lower() or "auto"
    if tts not in {"auto", "edge", "zerotts", "print"}:
        raise ValueError("COACH_TTS must be auto, edge, zerotts, or print")
    cdp_url = value("COACH_CDP_URL", "").strip()
    if cdp_url and not cdp_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("COACH_CDP_URL must use loopback HTTP")
    navigation_mode = value("COACH_NAV_MODE", "native_focus").strip().lower() or "native_focus"
    if navigation_mode not in {"native_focus", "coach_list", "mouse_cue"}:
        raise ValueError("COACH_NAV_MODE must be native_focus, coach_list, or mouse_cue")
    manifest_value = value("COACH_TARGET_MANIFEST", "").strip()
    lesson_value = value("COACH_LESSON_PDF", "").strip()
    return Settings(
        openai_api_key=value("OPENAI_API_KEY", "").strip(),
        openai_model=value("OPENAI_MODEL", "gpt-5-nano").strip() or "gpt-5-nano",
        llm_enabled=_flag(value("COACH_LLM", "false")),
        vision_enabled=_flag(value("COACH_VISION", "false")),
        mic_enabled=_flag(value("COACH_MIC", "false")),
        barge_in=_flag(value("COACH_BARGE_IN", "false")),
        headed=_flag(value("COACH_HEADED", "true")),
        tts=tts,
        edge_voice=value("COACH_EDGE_VOICE", "vi-VN-HoaiMyNeural").strip()
        or "vi-VN-HoaiMyNeural",
        whisper_model=value("COACH_WHISPER_MODEL", "vudang449/PhoWhisper-small-ct2").strip(),
        whisper_language=value("COACH_WHISPER_LANGUAGE", "vi").strip() or "vi",
        whisper_device=value("COACH_WHISPER_DEVICE", "gpu").strip() or "gpu",
        whisper_compute_type=value("COACH_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
        zerotts_model=value("COACH_ZEROTTS_MODEL", "zeroweight-ai/ZeroTTS").strip(),
        zerotts_voice=value("COACH_ZEROTTS_VOICE", "maichi").strip() or "maichi",
        zerotts_cache_dir=ROOT / value("COACH_ZEROTTS_CACHE_DIR", ".cache/zerotts"),
        sandbox_port=_port(value("COACH_SANDBOX_PORT", "8765")),
        cue_poll_seconds=_seconds(value("COACH_CUE_POLL_SECONDS", "0.35")),
        vad_min_volume=_fraction(value("COACH_VAD_MIN_VOLUME", "0.002"), "COACH_VAD_MIN_VOLUME"),
        egress_log=ROOT / value("COACH_EGRESS_LOG", "logs/egress.jsonl"),
        browser_audit_log=ROOT / value("COACH_BROWSER_AUDIT_LOG", "logs/browser-audit.jsonl"),
        cdp_url=cdp_url,
        allowed_origins=_origins(value("COACH_ALLOWED_ORIGINS", "")),
        target_tab_title=value("COACH_TARGET_TAB_TITLE", "").strip(),
        navigation_mode=navigation_mode,
        inject_navigation=_flag(value("COACH_INJECT_NAVIGATION", "false")),
        target_manifest=(ROOT / manifest_value) if manifest_value else None,
        agent_browser_bin=value("COACH_AGENT_BROWSER_BIN", "").strip(),
        lesson_pdf=(ROOT / lesson_value) if lesson_value else None,
        env_file=path,
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _flag(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _port(raw: str) -> int:
    port = int(raw)
    if not 0 <= port <= 65535:
        raise ValueError("COACH_SANDBOX_PORT is out of range")
    return port


def _seconds(raw: str) -> float:
    seconds = float(raw)
    if seconds <= 0:
        raise ValueError("COACH_CUE_POLL_SECONDS must be positive")
    return seconds


def _origins(raw: str) -> tuple[str, ...]:
    values = tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    for origin in values:
        if not origin.startswith(("http://", "https://")):
            raise ValueError("COACH_ALLOWED_ORIGINS entries must be origins")
    return values


def _fraction(raw: str, name: str) -> float:
    value = float(raw)
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value
