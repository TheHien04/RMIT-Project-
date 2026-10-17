from coach.llm import _complete_clauses


def test_streaming_llm_emits_only_complete_spoken_clauses():
    clauses, tail = _complete_clauses("Đi tới Table Editor. Sau đó nhấn")
    assert clauses == ["Đi tới Table Editor."]
    assert tail == "Sau đó nhấn"
