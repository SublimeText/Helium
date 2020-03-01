import sublime

from unittest import TestCase


class ViewTestCase(TestCase):
    """Providing basic functionality for testing against views.

    Taken from:
    https://github.com/randy3k/AlignTab/blob/master/tests/test_basic.py
    https://github.com/randy3k/AutoWrap/blob/master/tests/test_python.py
    """

    def setUp(self):
        # make sure we have a window to work with
        s = sublime.load_settings("Preferences.sublime-settings")
        s.set("close_windows_when_empty", False)
        self.view = sublime.active_window().new_file()

    def tearDown(self):
        if self.view:
            self.view.set_scratch(True)
            self.view.window().run_command("close_file")

    def setText(self, string):
        self.view.run_command("insert", {"characters": string})
