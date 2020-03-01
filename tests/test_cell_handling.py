import re
from unittest import TestCase

import sublime

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
