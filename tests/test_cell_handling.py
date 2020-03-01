import re
from unittest import TestCase

import sublime

from _helpers import ViewTestCase

good_delimiters = (
    # %% pattern
    "#%%",
    "# %%",
    # `in` pattern
    "# in[5]:",
    "# in[]:",
    "# in:",
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
    "in:",
    "# In[5]:",
    "# In[]:",
    "# In:"
)


class TestDelimiterRegex(TestCase):
    def setUp(self):
        s = sublime.load_settings("Helium.sublime-settings")
        self.rgx = re.compile(s.get("cell_delimiter_pattern"))

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

    def check_content_against_match_count(self, content, expected_count):
        self.clear_view()
        self.set_text(content)
        matches = self.find_all_delimiters()
        assert len(matches) == expected_count

    def test_view_find_pattern_one(self):
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# %% \n" * i, i)

    def test_view_find_pattern_two(self):
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# in: \n" * i, i)

    def test_view_find_patterns_mixed(self):
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# %% \n# in: \n" * i, i * 2)
