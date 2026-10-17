import json

import pytest

from coach.latency import LatencyTrace, assert_slo, report_file, summarize


def test_hundred_turn_benchmark_reports_p50_p95_and_max():
    samples = [100 + index for index in range(100)]
    summary = assert_slo(samples, p95_limit_ms=250)
    assert summary == {"p50": 149.5, "p95": 194, "max": 199}


def test_latency_benchmark_fails_when_p95_exceeds_slo():
    with pytest.raises(AssertionError, match="exceeds"):
        assert_slo([1600.0] * 100, p95_limit_ms=1500)
    assert summarize([3, 1, 2])["max"] == 3


def test_latency_report_reads_real_trace_file_and_requires_sample_floor(tmp_path):
    path = tmp_path / "latency.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "trace_id": f"browser-{index}",
                    "kind": "browser",
                    "durations_ms": {"audio_started": 100 + index},
                }
            )
            for index in range(100)
        ),
        encoding="utf-8",
    )
    report = report_file(path, kind="browser")
    assert report == {
        "samples": 100,
        "limit_ms": 250.0,
        "p50": 149.5,
        "p95": 194.0,
        "max": 199.0,
    }
    with pytest.raises(ValueError, match="at least 101"):
        report_file(path, kind="browser", min_samples=101)


def test_vision_latency_uses_vision_request_as_its_origin():
    trace = LatencyTrace("vision-1", "vision")
    trace.mark("vision_request", 10.0)
    trace.mark("guidance_ready", 12.25)
    assert trace.durations_ms() == {"guidance_ready": 2250.0}
