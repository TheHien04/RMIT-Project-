from coach.demo_run import run_lesson
from coach.lesson import plan_from_pages
from coach.observer import PageObserver
from coach.pdf_text import ONBOARDING_PAGES
from coach.privacy import EgressLog


def test_div_controls_have_boxes_and_no_role(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    observer = PageObserver(page)
    observer.install()
    page.mouse.move(20, 20)
    snapshot = observer.snapshot()
    create = snapshot.element_named("Tạo bảng")
    assert create is not None
    assert create.tag == "div"
    assert create.role is None
    assert create.tab_index < 0
    assert create.box.width > 20
    assert snapshot.cursor is not None
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement === document.body")


def test_button_flow_uses_real_buttons(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=button")
    snapshot = PageObserver(page).snapshot()
    create = snapshot.element_named("Tạo bảng")
    assert create.tag == "button"


def test_closed_loop_finishes_the_table_without_sending_data(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    log = EgressLog()
    speeches = run_lesson(page, plan_from_pages(ONBOARDING_PAGES), egress=log)
    text = " ".join(speech.text for speech in speeches)
    assert "Tạo bảng. Enter." in text
    assert "Thêm cột. Enter." in text
    assert "Lưu bảng. Enter." in text
    assert "Trang 2" in text
    assert page.evaluate("() => document.body.dataset.saved") == "true"
    assert all(not event.left_machine for event in log.events)
    assert any(event.kind == "llm" for event in log.events)
