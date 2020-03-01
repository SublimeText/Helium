import unittest


class TestThatTestsAreRunning(unittest.TestCase):
    def test_that_never_fails(self):
        """Check that tests are indeed being run."""
        self.assertTrue(True)
