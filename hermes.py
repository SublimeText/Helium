"""Hermes package for Sublime Text 3.

The package provides code execution and completion in interaction with Jupyter.
Copyright (c) 2016, NEGORO Tetsuya (https://github.com/ngr-t)
"""

import json
import re
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
            kernel = KernelConnection(name, kernel_id, cls)
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


class HermesSetUrl(WindowCommand):
    """Set url of jupyter process."""

    @staticmethod
    def run():
        """Command."""
        # TODO: read from config file
        connection_list = ["http://localhost:8888"]
        connection_list += ["Input url"]

        def callback(index):
            if index == len(connection_list):
                sublime.active_window().show_input_panel(
                    'URL: ', '', KernelManager.set_url, None, None)
            else:
                url = connection_list[index]
                KernelManager.set_url(url)
        sublime.active_window().show_quick_panel(
            connection_list, callback)


class HermesStartKernel(TextCommand):
    """Start a kernel and connect view to it."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        try:
            kernelspecs = KernelManager.list_kernelspecs()
        except:
            sublime.message_dialog("Set URL first, please.")
            sublime.active_window().run_command("hermes_set_url")
            return
        menu_items = list(kernelspecs["kernelspecs"].keys())

        def callback(index):
            selected_kernelspec = menu_items[index]
            kernel = KernelManager.start_kernel(selected_kernelspec)
            ViewManager.connect_kernel(
                self.view.buffer_id(),
                kernel.lang,
                kernel.kernel_id)
            if self.view.file_name():
                view_name = self.view.file_name()
            else:
                view_name = self.view.name()
            log_info_msg = (
                "Connected view '{view_name}(id: {buffer_id})'"
                "to kernel {kernel_id}.").format(
                view_name=view_name,
                buffer_id=self.view.buffer_id(),
                kernel_id=kernel.kernel_id)
            logger.info(log_info_msg)

        sublime.active_window().show_quick_panel(
            menu_items, callback)


class HermesConnectKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        try:
            kernel_list = KernelManager.list_kernels()
        except:
            sublime.message_dialog("Set URL first, please.")
            sublime.active_window().run_command("hermes_set_url")
            return
        menu_items = [
            "[{lang}] {kernel_id}".format(
                lang=kernel["name"],
                kernel_id=kernel["id"])
            for kernel
            in kernel_list]

        def callback(index):
            if index == len(kernel_list):
                self.view.run_command("hermes_start_kernel")
                return
            selected_kernel = kernel_list[index]
            ViewManager.connect_kernel(
                self.view.buffer_id(),
                selected_kernel["name"],
                selected_kernel["id"])
            if self.view.file_name():
                view_name = self.view.file_name()
            else:
                view_name = self.view.name()
            log_info_msg = (
                "Connected view '{view_name}(id: {buffer_id})'"
                "to kernel {kernel_id}.").format(
                view_name=view_name,
                buffer_id=self.view.buffer_id(),
                kernel_id=selected_kernel["id"])
            logger.info(log_info_msg)
        menu_items += ["New kernel"]
        sublime.active_window().show_quick_panel(
            menu_items, callback)


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



class HermesExecuteBlock(TextCommand):
    """Execute code."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except:
            sublime.message_dialog("No kernel is connected to this view.")
            self.view.run_command("hermes_connect_kernel")
        pre_code = []
        for s in self.view.sel():
            code = get_block(self.view, s)
            if code == pre_code:
                continue
            kernel.execute_code(code)
            log_info_msg = "Executed code {code} with kernel {kernel_id}".format(
                code=code,
                kernel_id=kernel.kernel_id)
            logger.info(log_info_msg)
            pre_code = code


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
