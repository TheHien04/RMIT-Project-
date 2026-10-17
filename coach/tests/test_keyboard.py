from coach.dom_map import PageControls
from coach.observer import PageObserver


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


def test_target_only_keyboard_repair_keeps_activation_with_the_learner(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    board = PageControls(page, inject_navigation=False)
    assert page.locator('[role="button"]').count() == 0
    assert board.repair_label("Tạo bảng")
    target = page.get_by_role("button", name="Tạo bảng")
    assert target.get_attribute("tabindex") == "0"
    assert page.evaluate("() => document.body.dataset.panel") == "closed"
    target.focus()
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.body.dataset.panel") == "open"
    assert not board.repair_label("không tồn tại")


def test_browser_action_is_denied_if_page_changes_after_target_lookup(page, sandbox_url):
    reviewed_url = sandbox_url + "/?flow=div"
    page.goto(reviewed_url)
    board = PageControls(page, inject_navigation=False)
    original = board._control_named

    def navigate_after_lookup(label):
        control = original(label)
        page.goto(sandbox_url + "/?flow=div&redirected=1")
        return control

    board._control_named = navigate_after_lookup
    assert not board.click_label(
        "Tạo bảng",
        expected_url=reviewed_url,
        allowed_origins=(sandbox_url,),
    )
    assert page.evaluate("() => document.body.dataset.panel") == "closed"


def test_target_only_repair_handles_a_react_style_delegated_pointer_card(page):
    page.set_content(
        """
        <main>
          <div id="create-card" style="cursor: pointer">
            <h3>Create a table</h3>
            <p>Design and create a new database table</p>
          </div>
        </main>
        <script>
          document.addEventListener("click", (event) => {
            if (event.target.closest("#create-card")) document.body.dataset.open = "true";
          });
        </script>
        """
    )
    board = PageControls(page, inject_navigation=False)
    assert all(control.text != "Create a table" for control in board.detect())

    assert board.repair_label("Create a table")
    target = page.get_by_role("button", name="Create a table")
    assert target.get_attribute("id") == "create-card"
    assert page.evaluate("() => document.body.dataset.open || 'false'") == "false"

    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.id") == "create-card"
    page.keyboard.press("Enter")
    assert page.evaluate("() => document.body.dataset.open") == "true"


def test_detect_uses_form_labels_and_ignores_aria_hidden_shortcut_text(page):
    page.set_content(
        """
        <label for="name">Name</label><input id="name">
        <button><span>Save</span><span aria-hidden="true">⌘↵</span></button>
        <button aria-label="Create a table" title="Create a new table"></button>
        """
    )
    controls = PageControls(page, inject_navigation=False).detect()
    assert [control.text for control in controls] == ["Name", "Save", "Create a table"]


def test_create_table_repairs_type_primary_and_new_column_focus(page):
    page.set_content(
        """
        <input data-testid="table-name-input">
        <button id="type" role="combobox" aria-expanded="false">int8</button>
        <button id="primary" role="checkbox"
                aria-label="Check to make this column a primary key"
                aria-checked="false"></button>
        <div id="columns"><input aria-label="Column name" value="id"></div>
        <button id="add">Add column</button>
        <script>
          primary.addEventListener('click', () => {
            primary.setAttribute('aria-checked',
              primary.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
          });
          add.addEventListener('click', () => {
            const input = document.createElement('input');
            input.setAttribute('aria-label', 'Column name');
            columns.appendChild(input);
          });
        </script>
        """
    )
    board = PageControls(page, inject_navigation=False)
    assert board.install_form_accessibility()
    assert page.locator("#type").get_attribute("aria-label") == "Column type, current int8"
    page.locator("#type").focus()
    assert PageObserver(page).snapshot().focused_text == "Type, hiện tại int8"

    page.locator("#primary").focus()
    page.keyboard.press("Enter")
    assert board.process_form_accessibility_action() == "primary_enter"
    assert page.locator("#primary").get_attribute("aria-checked") == "true"
    assert PageObserver(page).snapshot().focused_text == "Primary, đang chọn"

    page.locator("#add").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(75)
    assert page.locator('input[aria-label="Column name"]').count() == 2
    assert PageObserver(page).snapshot().focused_text == "Column name"


def test_type_arrow_option_is_exposed_as_the_focused_description(page):
    page.set_content(
        """
        <input data-testid="table-name-input">
        <input id="search" role="combobox" placeholder="Search types..."
               aria-activedescendant="int4-option">
        <div id="int4-option" role="option">int4 Signed four-byte integer</div>
        <div id="int8-option" role="option">int8 Signed eight-byte integer</div>
        """
    )
    page.locator("#search").focus()
    observer = PageObserver(page)
    assert observer.snapshot().focused_text == "Type option, int4 Signed four-byte integer"
    page.locator("#search").evaluate(
        "el => el.setAttribute('aria-activedescendant', 'int8-option')"
    )
    assert observer.snapshot().focused_text == "Type option, int8 Signed eight-byte integer"
