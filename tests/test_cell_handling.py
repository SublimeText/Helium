import re
from unittest import TestCase

import sublime

from _helpers import ViewTestCase

good_delimiters = (
    # %% pattern
    "#%%",
    "# %%",
    # `in` pattern
    "# In[5]:",
    "# In[]:",
    "# In:",
    "#In:",
    "#in:"
)

bad_delimiters = (
    "#",
    "#%",
    "#%?",
    "%",
    "% 123",
    "no way",
    "# normal comment",
    "#xin:",
    "#        in:",
    "# in",
    "in:"
)


class TestDelimiterRegex(TestCase):
    def setUp(self):
        s = sublime.load_settings("Helium.sublime-settings")
        self.rgx = re.compile(s.get("cell_delimiter_pattern"), re.I)

    # Note: ST does not use python re for view.findall internall
    # see: https://forum.sublimetext.com/t/question-about-view-find-find-all-pattern/33682
    # We want some basic re tests nonetheless
    def test_good_delimiters_matched(self):
        for d in good_delimiters:
            # TODO: Use subTest once on ST4
            match = self.rgx.match(d)
            self.assertTrue(match)

    def test_bad_delimiters_not_matched(self):
        for d in bad_delimiters:
            # TODO: Use subTest once on ST4
            match = self.rgx.match(d)
            self.assertIsNone(match)


class TestDelimiterSearch(ViewTestCase):

    def find_all_delimiters(self):
        s = sublime.load_settings("Helium.sublime-settings")
        pattern = s.get("cell_delimiter_pattern")
        return self.view.find_all(pattern)

    def test_view_find_all(self):
        self.setText("")
        matches = self.find_all_delimiters()
        assert len(matches) == 0

    def test_view_find_one(self):
        self.setText("# %%")
        matches = self.find_all_delimiters()
        assert len(matches) == 1
