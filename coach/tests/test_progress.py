import stat

from coach.lesson import plan_from_pages
from coach.progress import AssistanceLevel, ProgressStore


def test_progress_fades_instruction_per_skill_and_persists(tmp_path):
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    path = tmp_path / "progress.json"
    store = ProgressStore(path)
    key = store.skill_key("Bài", step)
    assert store.level_for(key) is AssistanceLevel.ORIENTATION

    store.start_attempt(key, page_version="v1")
    store.complete(key)
    assert store.level_for(key) is AssistanceLevel.ORIENTATION
    assert store.suggested_level_for(key) is AssistanceLevel.GUIDED
    store.accept_level(key, AssistanceLevel.GUIDED)
    store.start_attempt(key, page_version="v1")
    store.complete(key)
    assert store.suggested_level_for(key) is AssistanceLevel.PRACTICE
    store.accept_level(key, AssistanceLevel.PRACTICE)
    store.start_attempt(key, page_version="v1")
    store.complete(key)
    assert store.suggested_level_for(key) is AssistanceLevel.ON_DEMAND
    store.accept_level(key, AssistanceLevel.ON_DEMAND)
    persisted = ProgressStore(path).get(key)
    assert persisted.successful_without_hint == 3
    assert persisted.assistance_level == AssistanceLevel.ON_DEMAND.value
    assert persisted.time_to_complete is not None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_help_prevents_false_mastery_and_page_change_reduces_confidence(tmp_path):
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    store = ProgressStore(tmp_path / "progress.json")
    key = store.skill_key("Bài", step)
    store.start_attempt(key, page_version="v1")
    store.record_hint(key, 2)
    store.complete(key)
    assert store.get(key).successful_without_hint == 0

    store.get(key).successful_without_hint = 3
    store.start_attempt(key, page_version="v2")
    assert store.get(key).successful_without_hint == 2


def test_focus_loop_is_not_counted_as_independent_success():
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    store = ProgressStore()
    key = store.skill_key("Bài", step)
    store.start_attempt(key, page_version="v1")
    store.record_focus_loop(key)
    store.complete(key)
    assert store.get(key).focus_loops == 1
    assert store.get(key).successful_without_hint == 0


def test_user_confirmed_completion_is_persisted_without_claiming_mastery(tmp_path):
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    path = tmp_path / "progress.json"
    store = ProgressStore(path)
    key = store.skill_key("Bài", step)

    store.start_attempt(key, page_version="v1")
    store.complete(key, source="user_confirmed")

    persisted = ProgressStore(path).get(key)
    assert persisted.status == "completed"
    assert persisted.completion_source == "user_confirmed"
    assert persisted.successful_without_hint == 0


def test_paused_attempt_stays_incomplete_and_is_persisted(tmp_path):
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    path = tmp_path / "progress.json"
    store = ProgressStore(path)
    key = store.skill_key("Bài", step)

    store.start_attempt(key, page_version="v1")
    store.pause(key)

    persisted = ProgressStore(path).get(key)
    assert persisted.status == "paused"
    assert persisted.completion_source == ""
    assert persisted.last_success is None


def test_independent_streak_resets_after_help_and_followups_store_no_content(tmp_path):
    step = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".']).steps[0]
    path = tmp_path / "progress.json"
    store = ProgressStore(path)
    key = store.skill_key("Bài", step)

    store.start_attempt(key, page_version="v1")
    store.complete(key)
    assert store.get(key).independent_success_streak == 1
    store.start_attempt(key, page_version="v1")
    store.record_hint(key, 1)
    store.complete(key)
    store.record_learning_followup(key, reflection=True, transfer=True)

    persisted = ProgressStore(path).get(key)
    assert persisted.independent_success_streak == 0
    assert persisted.reflection_prompts == 1
    assert persisted.transfer_tasks_offered == 1
    raw = path.read_text(encoding="utf-8")
    assert "transcript" not in raw
    assert "Bạn đã dùng phím nào" not in raw
