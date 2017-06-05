from functools import wraps
import re

import sublime
from sublime_plugin import TextCommand


def chain_callbacks(f):
    # type: Callable[..., Generator[Callable[Callable[...], Any, Any]] -> Callable[..., Any]
    """Decorator to enable mimicing promise pattern by yield expression.

    Decorator function to make a wrapper which executes functions
    yielded by the given generator in order."""
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
        """The command definition."""
        s = self.view.size()
        region = sublime.Region(0, s)
        self.view.replace(edit, region, s * "*")


def show_password_input(prompt, cb):
    hidden_input = ""
    view = None

    def get_hidden_input(user_input):
        nonlocal hidden_input
        cb(hidden_input)

    def hide_input(user_input):
        nonlocal view
        nonlocal hidden_input

        matches = PASSWORD_INPUT_PATTERN.match(user_input)
        if matches:
            # When there are characters other than "*"
            pre, new, post = matches.group(1, 2, 3)
            hidden_input = hidden_input[:len(pre)] + new + hidden_input[len(hidden_input)-len(post):len(hidden_input)]
            view.run_command("mask_input_panel_text")
        else:
            try:
                pos = view.sel()[0].begin()
                hidden_input = hidden_input[:pos] + hidden_input[pos:len(user_input)]
            except AttributeError:
                # `view` is not assigned at first time this function is called.
                pass

    view = (
        sublime
        .active_window()
        .show_input_panel(
            prompt,
            "",
            get_hidden_input,
            hide_input,
            lambda: None)
    )
