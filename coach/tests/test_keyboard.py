from coach.dom_map import PageControls


def test_arrows_walk_clickable_divs_and_enter_activates(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    board = PageControls(page)
    board.install()
    assert board.set_navigation(True)
    controls = board.detect()
    assert [control.text for control in controls] == ["Tạo bảng", "Thêm cột", "Lưu bảng"]
    assert {control.tag for control in controls} == {"div"}
    assert {control.reason for control in controls} == {"click-listener"}
    state = board.read()
    assert state.index == -1
    assert state.label == ""
    assert page.evaluate("() => document.body.dataset.panel") == "closed"

    page.keyboard.press("ArrowDown")
    assert board.read().label == "Tạo bảng"
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.body.dataset.panel") == "open"
    assert board.read().label == "Tạo bảng"

    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement === document.body")


def test_coach_list_is_explicit_and_escape_returns_page_reading(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    board = PageControls(page)
    board.install()
    page.keyboard.press("ArrowDown")
    assert board.read().label == ""
    assert board.set_navigation(True)
    page.keyboard.press("ArrowDown")
    assert board.read().label == "Tạo bảng"
    page.keyboard.press("Escape")
    assert board.read().enabled is False
