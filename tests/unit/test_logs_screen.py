from src.tui.screens.logs import LogsScreen


class DummyLog:
    def __init__(self):
        self.auto_scroll = False
        self.lines = []
        self.scroll_end_calls = []
        self.scroll_home_calls = 0
        self.scroll_up_calls = 0
        self.scroll_page_up_calls = 0

    def write_line(self, line: str) -> None:
        self.lines.append(line)

    def scroll_end(self, animate=False):
        self.scroll_end_calls.append(animate)

    def scroll_home(self):
        self.scroll_home_calls += 1

    def scroll_up(self):
        self.scroll_up_calls += 1

    def scroll_page_up(self):
        self.scroll_page_up_calls += 1

    def scroll_down(self):
        pass

    def scroll_page_down(self):
        pass

    def clear(self):
        self.lines.clear()


def make_screen() -> LogsScreen:
    screen = LogsScreen()
    screen.logs_area = DummyLog()
    screen.notify = lambda *args, **kwargs: None
    return screen


def test_append_log_line_scrolls_when_tail_following_enabled():
    screen = make_screen()

    screen.auto_scroll_enabled = True
    screen._append_log_line("hello")

    assert screen.logs_area.lines == ["hello"]
    assert screen.logs_area.scroll_end_calls == [False]


def test_scroll_top_disables_auto_scroll_before_scrolling_home():
    screen = make_screen()
    screen.auto_scroll_enabled = True

    screen.action_scroll_top()

    assert screen.auto_scroll_enabled is False
    assert screen.logs_area.scroll_home_calls == 1


def test_scroll_bottom_reenables_auto_scroll_and_jumps_to_end():
    screen = make_screen()
    screen.auto_scroll_enabled = False

    screen.action_scroll_bottom()

    assert screen.auto_scroll_enabled is True
    assert screen.logs_area.scroll_end_calls == [False]


def test_manual_scroll_up_disables_tail_following():
    screen = make_screen()
    screen.auto_scroll_enabled = True

    screen.action_scroll_up()

    assert screen.auto_scroll_enabled is False
    assert screen.logs_area.scroll_up_calls == 1


def test_toggle_auto_scroll_enables_and_disables_manual_tail_following():
    screen = make_screen()

    screen.action_toggle_auto_scroll()
    assert screen.auto_scroll_enabled is False
    assert screen.logs_area.scroll_end_calls == []

    screen.action_toggle_auto_scroll()
    assert screen.auto_scroll_enabled is True
    assert screen.logs_area.scroll_end_calls == [False]
