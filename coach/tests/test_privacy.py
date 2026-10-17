from pathlib import Path
import stat

from coach.privacy import BrowserAudit, EgressLog, consider_icon


def test_vision_is_blocked_unless_enabled():
    log = EgressLog()
    assert consider_icon(b"\x89PNG", vision_enabled=False, egress=log) is False
    assert log.events[0].left_machine is False
    assert consider_icon(b"\x89PNG", vision_enabled=True, egress=log) is True
    assert log.events[1].left_machine is True


def test_browser_audit_redacts_sensitive_values_and_omits_raw_page_data(tmp_path):
    audit = BrowserAudit()
    audit.record(
        "attached",
        origin="https://supabase.com",
        token="secret",
        dom="<html>private</html>",
        url="https://supabase.com/dashboard?api_key=secret",
    )
    assert audit.events == [
        {
            "kind": "attached",
            "summary": {
                "origin": "https://supabase.com",
                "url": "[redacted]",
            },
        }
    ]
    path = Path(tmp_path) / "audit.jsonl"
    audit.write_jsonl(path)
    assert "secret" not in path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_egress_log_hashes_spoken_content_and_is_owner_only(tmp_path):
    log = EgressLog()
    log.record(
        "llm",
        {
            "user_text": "mật khẩu của tôi là bí mật",
            "step_say": "nội dung bài học",
            "citation_quote": "trích dẫn",
            "target_label": "Tạo bảng",
        },
        left_machine=False,
    )
    path = Path(tmp_path) / "egress.jsonl"
    log.write_jsonl(path)
    content = path.read_text(encoding="utf-8")
    assert "mật khẩu" not in content
    assert "nội dung bài học" not in content
    assert "trích dẫn" not in content
    assert "user_text_sha256" in content
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
