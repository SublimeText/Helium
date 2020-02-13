import re
import sys
from functools import wraps

import sublime
from sublime_plugin import TextCommand


class add_path(object):
    """Temporarily insert a path into sys.path."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):  # noqa
        sys.path.insert(0, self.path)

    def __exit__(self, exc_type, exc_value, traceback):  # noqa
        sys.path.remove(self.path)


def chain_callbacks(f):
    """Decorate to mimic the promise pattern via an yield expression.

    Decorator function to make a wrapper which executes functions
    yielded by the given generator in order.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        chain = f(*args, **kwargs)
        try:
            next_f = next(chain)
        except StopIteration:
            return

        def cb(*args, **kwargs):
            nonlocal next_f
            try:
                if len(args) + len(kwargs) != 0:
                    next_f = chain.send(*args, **kwargs)
                else:
                    next_f = next(chain)
                next_f(cb)
            except StopIteration:
                return

        next_f(cb)

    return wrapper


PASSWORD_INPUT_PATTERN = re.compile(r"^(\**)([^*]+)(\**)")


class MaskInputPanelText(TextCommand):
    """Command to hide all the charatcters of view by '*'."""

    def run(self, edit):
        s = self.view.size()
        region = sublime.Region(0, s)
        self.view.replace(edit, region, s * "*")


def show_password_input(prompt, on_done, on_cancel):
    hidden_input = ""
    view = None

    def get_hidden_input(user_input):
        nonlocal hidden_input
        on_done(hidden_input)

    def hide_input(user_input):
        nonlocal view
        nonlocal hidden_input

        matches = PASSWORD_INPUT_PATTERN.match(user_input)
        if matches:
            # When there are characters other than "*"
            pre, new, post = matches.group(1, 2, 3)
            hidden_input = (
                hidden_input[: len(pre)]
                + new
                + hidden_input[len(hidden_input) - len(post) : len(hidden_input)]
            )
            view.run_command("mask_input_panel_text")
        else:
            try:
                pos = view.sel()[0].begin()
                hidden_input = hidden_input[:pos] + hidden_input[pos : len(user_input)]
            except AttributeError:
                # `view` is not assigned at first time this function is called.
                pass

    view = sublime.active_window().show_input_panel(
        prompt, "", get_hidden_input, hide_input, on_cancel
    )
