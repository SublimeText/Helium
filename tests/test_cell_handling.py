import sublime

from _helpers import ViewTestCase

valid_delimiters = (
    # %% pattern
    "#%%",
    "# %%",
    # `in` pattern
    "# in[5]:",
    "# in[]:",
    "# in:",
    "#in:"
)

invalid_delimiters = (
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


class TestDelimiter(ViewTestCase):

    def find_all_delimiters(self):
        s = sublime.load_settings("Helium.sublime-settings")
        pattern = s.get("cell_delimiter_pattern")
        return self.view.find_all(pattern)

    def check_content_against_match_count(self, content, expected_count):
        self.clear_view()
        self.set_text(content)
        matches = self.find_all_delimiters()
        assert len(matches) == expected_count

    def test_pattern_against_delimiteres_valid(self):
        """Succeed if all of the valid delimiters match."""
        for d in valid_delimiters:
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count(d, 1)

    def test_pattern_against_delimiteres_invalid(self):
        """Succeed if none of the invalid delimiters match."""
        for d in invalid_delimiters:
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count(d, 0)

    def test_delimiter_match_count_against_pattern_one(self):
        """Succeed if match count from view.find_all equal its expectation."""
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# %% \n" * i, i)

    def test_delimiter_match_count_against_pattern_two(self):
        """Succeed if match count from view.find_all equal its expectation."""
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# in: \n" * i, i)

    def test_delimiter_match_count_against_pattern_mixed(self):
        """Succeed if match count from view.find_all equal its expectation."""
        for i in range(10):
            # TODO: Use subTest once on ST4
            self.check_content_against_match_count("# %% \n# in: \n" * i, i * 2)
