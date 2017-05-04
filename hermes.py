"""Hermes package for Sublime Text 3.

The package provides code execution and completion in interaction with Jupyter.
Copyright (c) 2016, NEGORO Tetsuya (https://github.com/ngr-t)
"""

import json
import re
from functools import (partial, wraps)
from logging import getLogger, INFO, StreamHandler

import sublime
from sublime_plugin import WindowCommand, TextCommand, EventListener
from .kernel import KernelConnection

import requests

# Logger setting
HANDLER = StreamHandler()
HANDLER.setLevel(INFO)
HERMES_LOGGER = getLogger(__name__)
HERMES_LOGGER.setLevel(INFO)
HERMES_LOGGER.addHandler(HANDLER)

# Regex patterns to extract code lines.
INDENT_PATTERN = re.compile(r"^([ \t]*)")


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
                    chain.send(*args, **kwargs)
                next_f = next(chain)
                next_f(cb)
            except StopIteration:
                return
        next_f(cb)
    return wrapper


class ViewManager(object):
    """Manage the relation of views and kernels."""

    view_kernel_table = dict()

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "__instance__"):
            cls.__instance__ = super(ViewManager, object).__new__(
                cls, *args, **kwargs)
        return cls.__instance__

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def connect_kernel(cls, buffer_id, lang, kernel_id):
        """Connect view to kernel."""
        kernel = KernelManager.get_kernel(
            lang, kernel_id)
        cls.view_kernel_table[buffer_id] = kernel
        kernel.activate_view()

    @classmethod
    def remove_view(cls, view_name):
        """Remove view from manager."""
        if view_name in cls.view_kernel_table:
            del cls.view_kernel_table[view_name]

    @classmethod
    def get_kernel_for_view(cls, buffer_id) -> KernelConnection:
        """Get Kernel instance corresponding to the buffer_id."""
        return cls.view_kernel_table[buffer_id]


class KernelManager(object):
    """Manage Jupyter kernels."""

    kernels = dict()

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, "__instance__"):
            cls.__instance__ = super(KernelManager, object).__new__(
                cls, *args, **kwargs)
        return cls.__instance__

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def set_url(
        cls,
        base_url,
        base_ws_url=None,
    ):
        """Initialize a kernel manager.

        TODO: Deal with authentication.
        """
        if base_ws_url is None:
            _, _, url_body = base_url.partition("://")
            base_ws_url = "ws://" + url_body
        cls._base_url = base_url
        cls._base_ws_url = base_ws_url

    @classmethod
    def base_url(cls):
        """Base url of the jupyter process."""
        return cls._base_url

    @classmethod
    def base_ws_url(cls):
        """Base WebSocket URL of the jupyter process."""
        return cls._base_ws_url

    @classmethod
    def list_kernelspecs(cls):
        """Get the kernelspecs."""
        url = '{}/api/kernelspecs'.format(cls.base_url())
        response = requests.get(url)
        return response.json()

    @classmethod
    def list_kernels(cls):
        """Get the list of kernels."""
        url = '{}/api/kernels'.format(cls.base_url())
        response = requests.get(url)
        return response.json()

    @classmethod
    def get_kernel(cls, name, kernel_id):
        """Get KernelConnection object."""
        if (name, kernel_id) in cls.kernels:
            return cls.kernels[(name, kernel_id)]
        else:
            kernel = KernelConnection(
                name,
                kernel_id,
                cls,
                logger=HERMES_LOGGER)
            cls.kernels[(name, kernel_id)] = kernel
            return kernel

    @classmethod
    def start_kernel(cls, name):
        """Start kernel and return a `Kernel` instance."""
        url = '{}/api/kernels'.format(cls.base_url())
        data = dict(name=name)
        response = requests.post(
            url,
            data=json.dumps(data)).json()
        return KernelConnection(
            lang=response["name"],
            kernel_id=response["id"],
            manager=cls)


@chain_callbacks
def _set_url(window, *, continue_cb=lambda: None):
    # TODO: read from config file
    connection_list = ["http://localhost:8888"]
    connection_list += ["Input url"]

    index = yield partial(
        window.show_quick_panel,
        connection_list)
    if index == -1:
        return
    if index == len(connection_list):
        sublime.active_window().show_input_panel(
            'URL: ', '', KernelManager.set_url, None, None)
    else:
        url = connection_list[index]
        KernelManager.set_url(url)
    continue_cb()


class HermesSetUrl(WindowCommand):
    """Set url of jupyter process."""

    def run(self):
        """Command."""
        _set_url(self.window)


@chain_callbacks
def _start_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    try:
        kernelspecs = KernelManager.list_kernelspecs()
    except requests.RequestException:
        sublime.message_dialog("Set URL first, please.")
        window = sublime.active_window()
        yield partial(_set_url, window)

    menu_items = list(kernelspecs["kernelspecs"].keys())

    index = yield partial(
        window.show_quick_panel,
        menu_items)

    if index == -1:
        return
    selected_kernelspec = menu_items[index]
    kernel = KernelManager.start_kernel(selected_kernelspec)
    ViewManager.connect_kernel(
        view.buffer_id(),
        kernel.lang,
        kernel.kernel_id)
    if view.file_name():
        view_name = view.file_name()
    else:
        view_name = view.name()
    log_info_msg = (
        "Connected view '{view_name}(id: {buffer_id})'"
        "to kernel {kernel_id}.").format(
        view_name=view_name,
        buffer_id=view.buffer_id(),
        kernel_id=kernel.kernel_id)
    logger.info(log_info_msg)

    continue_cb()


class HermesStartKernel(TextCommand):
    """Start a kernel and connect view to it."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _start_kernel(sublime.active_window(), self.view)


@chain_callbacks
def _connect_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    try:
        kernel_list = KernelManager.list_kernels()
    except (requests.RequestException, AttributeError):
        sublime.message_dialog("Set URL first, please.")
        yield lambda cb: _set_url(window, continue_cb=cb)
        kernel_list = KernelManager.list_kernels()

    menu_items = [
        "[{lang}] {kernel_id}".format(
            lang=kernel["name"],
            kernel_id=kernel["id"])
        for kernel
        in kernel_list]
    menu_items += ["New kernel"]

    index = yield partial(
        window.show_quick_panel,
        menu_items)

    if index == -1:
        return
    elif index == len(kernel_list):
        yield partial(_start_kernel, window, view)
    else:
        selected_kernel = kernel_list[index]
        ViewManager.connect_kernel(
            view.buffer_id(),
            selected_kernel["name"],
            selected_kernel["id"])
        if view.file_name():
            view_name = view.file_name()
        else:
            view_name = view.name()
        log_info_msg = (
            "Connected view '{view_name}(id: {buffer_id})'"
            "to kernel {kernel_id}.").format(
            view_name=view_name,
            buffer_id=view.buffer_id(),
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)

    continue_cb()


class HermesConnectKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _connect_kernel(sublime.active_window(), self.view, logger=logger)


def get_line(view: sublime.View, row: int) -> str:
    """Get the code line under the cursor."""
    point = view.text_point(row, 0)
    line_region = view.line(point)
    return view.substr(line_region)


def get_indent(view: sublime.View, row: int) -> str:
    line = get_line(view, row)
    return INDENT_PATTERN.match(line).group()


def get_block(view: sublime.View, s: sublime.Region) -> str:
    """Get the code block under the cursor.

    The code block is the lines satisfying the following conditions:

      - Includes the line under the cursor.
      - Includes no blank line.
      - More indented than that of the line under the cursor.
    """
    view_end_row = view.rowcol(view.size())[0]
    current_row = view.rowcol(s.begin())[0]
    current_indent = get_indent(view, current_row)
    for first_row in range(current_row, -1, -1):
        indent = get_indent(view, first_row)
        if (not indent.startswith(current_indent) or
            get_line(view, first_row).strip() == ''
        ):
            break
    for last_row in range(current_row, view_end_row):
        indent = get_indent(view, last_row)
        if (not indent.startswith(current_indent) or
            get_line(view, last_row).strip() == ''
        ):
            break
    block_region = sublime.Region(
        view.text_point(first_row + 1, 0),
        view.text_point(last_row, 0) - 1)
    return view.substr(block_region)


def get_chunk(view: sublime.View, s: sublime.Region) -> str:
    """Get the code chunk under the cursor.

    A code chunk is a region separated by comments indicating chunks."""
    raise NotImplementedError


@chain_callbacks
def _execute_block(view, *, logger=HERMES_LOGGER):
    try:
        kernel = ViewManager.get_kernel_for_view(view.buffer_id())
    except KeyError:
        sublime.message_dialog("No kernel is connected to this view.")
        yield lambda cb: _connect_kernel(
            sublime.active_window(),
            view,
            continue_cb=cb)
        kernel = ViewManager.get_kernel_for_view(view.buffer_id())

    pre_code = []
    for s in view.sel():
        code = get_block(view, s)
        if code == pre_code:
            continue
        kernel.execute_code(code)
        log_info_msg = "Executed code {code} with kernel {kernel_id}".format(
            code=code,
            kernel_id=kernel.kernel_id)
        logger.info(log_info_msg)
        pre_code = code


class HermesExecuteBlock(TextCommand):
    """Execute code."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _execute_block(self.view, logger=logger)


class HermesCompleter(EventListener):
    """Completer."""

    def on_query_completions(
        self, view, prefix, locations, *,
        logger=HERMES_LOGGER
    ):
        """Get completions from the jupyter kernel."""
        try:
            # TODO: provide the way to toggle completion from the package.
            # TODO: It's better to get code from buffer, not prefix.
            kernel = ViewManager.get_kernel_for_view(view.buffer_id())
            return [
                (completion, ) * 2
                for completion
                in kernel.get_complete(prefix, len(prefix))]
        except KeyError:
            pass
