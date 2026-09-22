import subprocess

from coach.agent_browser import AgentBrowserSnapshot


def test_agent_browser_snapshot_is_read_only_and_parses_accessible_refs(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            '{"success":true,"data":{"refs":{"e1":{"role":"button","name":"Tạo dự án"}}}}',
            "",
        )

    monkeypatch.setattr("coach.agent_browser.subprocess.run", fake_run)
    snapshot = AgentBrowserSnapshot("http://127.0.0.1:9222", binary="agent-browser")
    assert snapshot.controls()[0].name == "Tạo dự án"
    command = seen["command"]
    assert "snapshot" in command
    assert "-i" in command
    assert not {"click", "fill", "open", "eval"}.intersection(command)
