"""Hermes package for Sublime Text 3.

The package provides code execution and completion in interaction with Jupyter.
Copyright (c) 2016, NEGORO Tetsuya (https://github.com/ngr-t)
"""

import json
import re
from functools import partial
from logging import getLogger, INFO, StreamHandler

import sublime
from sublime_plugin import (
    WindowCommand,
    TextCommand,
    EventListener,
    ViewEventListener)
from .kernel import KernelConnection

import requests
from websocket import WebSocketTimeoutException

from .utils import chain_callbacks

# Logger setting
HERMES_LOGGER = getLogger(__name__)
HANDLER = StreamHandler()
HANDLER.setLevel(INFO)

if len(HERMES_LOGGER.handlers) == 0:
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
        auth=None,
        token=None
    ):
        """Initialize a kernel manager.

        TODO: Deal with password authorization.
        Importance is low because token authorization is possible.
        """
        base_url = base_url.rstrip("/")
        if base_ws_url is None:
            protocol, _, url_body = base_url.partition("://")
            if protocol == "https":
                base_ws_url = "wss://" + url_body
            else:
                base_ws_url = "ws://" + url_body
        else:
            base_ws_url = base_ws_url.rstrip("/")
        cls._base_url = base_url
        cls._base_ws_url = base_ws_url
        cls._auth = auth
        cls._token = token
        try:
            # Check if we can connect to the kernel gateway
            # via passed information.
            cls.list_kernelspecs()
        except requests.RequestException:
            # If we can't, remove member attributes.
            sublime.message_dialog("Invalid URL or token.")
            del cls._base_url
            del cls._base_ws_url
            del cls._auth
            del cls._token

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
        return cls.get_request(url)

    @classmethod
    def list_kernels(cls):
        """Get the list of kernels."""
        url = '{}/api/kernels'.format(cls.base_url())
        return cls.get_request(url)

    @classmethod
    def get_kernel(cls, name, kernel_id):
        """Get KernelConnection object."""
        if (name, kernel_id) in cls.kernels:
            return cls.kernels[(name, kernel_id)]
        else:
            if cls._token:
                kernel = KernelConnection(
                    name,
                    kernel_id,
                    cls,
                    auth_type="token",
                    token=cls._token,
                    logger=HERMES_LOGGER)
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
        response = cls.post_request(
            url,
            data=json.dumps(data))
        return KernelConnection(
            lang=response["name"],
            kernel_id=response["id"],
            manager=cls)

    @classmethod
    def shutdown_kernel(cls, kernel_id):
        url = '{base_url}/api/kernels/{kernel_id}'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        cls.delete_request(url)

    @classmethod
    def restart_kernel(cls, kernel_id):
        url = '{base_url}/api/kernels/{kernel_id}/restart'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        cls.post_request(url, dict())

    @classmethod
    def interrupt_kernel(cls, kernel_id):
        url = '{base_url}/api/kernels/{kernel_id}/interrupt'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        cls.post_request(url, dict())

    @classmethod
    def post_request(cls, url, data):
        if cls._token:
            header_auth_body = "token {token}".format(
                token=cls._token)
            header = dict(Authorization=header_auth_body)
        else:
            header = dict()
        response = requests.post(
            url,
            data=data,
            headers=header)
        return response.json()

    @classmethod
    def get_request(cls, url):
        if cls._token:
            header_auth_body = "token {token}".format(
                token=cls._token)
            header = dict(Authorization=header_auth_body)
        else:
            header = dict()
        response = requests.get(
            url,
            headers=header)
        return response.json()

    @classmethod
    def delete_request(cls, url):
        if cls._token:
            header_auth_body = "token {token}".format(
                token=cls._token)
            header = dict(Authorization=header_auth_body)
        else:
            header = dict()
        response = requests.delete(
            url,
            headers=header)
        return response.json()


@chain_callbacks
def _set_url(window, *, continue_cb=lambda: None):
    settings = sublime.load_settings("Hermes.sublime-settings")
    connections = settings.get("connections", [])
    connection_menu_items = [
        [connection["name"], connection["url"]]
        for connection in connections
    ]
    connection_menu_items += [["New", "Input a new URL."]]

    connection_id = yield partial(
        window.show_quick_panel,
        connection_menu_items)
    if connection_id == -1:
        return
    elif connection_id == len(connection_menu_items) - 1:
        # When 'new' is chosen.
        url = yield lambda cb: window.show_input_panel(
            'URL: ',
            '',
            cb,
            on_change=lambda x: None,
            on_cancel=lambda: None)
    else:
        url = connections[connection_id]["url"]
    try:
        token = connections[connection_id]["token"]
    except (KeyError, IndexError):
        token = yield lambda cb: window.show_input_panel(
            "token",
            "",
            cb,
            lambda x: None,
            lambda: None)
    if token:
        KernelManager.set_url(url, token=token)
    else:
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
    continue_cb=lambda: None,
    *,
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
    _set_status_updater(view)
    continue_cb()


class HermesConnectKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _connect_kernel(sublime.active_window(), self.view, logger=logger)


@chain_callbacks
def _show_kernel_selection_menu(window, view, cb):
    # Get the kernel ID related to `view` if exists.
    try:
        current_kernel_id = ViewManager.get_kernel_for_view(view.buffer_id()).kernel_id
    except KeyError:
        result = re.match(r"\*Hermes Output\* \[.*?\] ([\w-]*)", view.name())
        if result:
            current_kernel_id = result.group(1)
        else:
            current_kernel_id = ""
    try:
        kernel_list = KernelManager.list_kernels()
    except (requests.RequestException, AttributeError):
        sublime.message_dialog("Set URL first, please.")
        yield lambda cb: _set_url(window, continue_cb=cb)
        kernel_list = KernelManager.list_kernels()

    menu_items = [
        "[{lang}] {kernel_id} (connected to this view)".format(lang=kernel["name"], kernel_id=kernel["id"])
        if kernel["id"] == current_kernel_id
        else "[{lang}] {kernel_id}".format(lang=kernel["name"], kernel_id=kernel["id"])
        for kernel
        in kernel_list]
    index = yield partial(
        window.show_quick_panel,
        menu_items)
    if index == -1:
        selected_kernel = None
    else:
        selected_kernel = kernel_list[index]
    cb(selected_kernel)


@chain_callbacks
def _interrupt_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    selected_kernel = yield partial(_show_kernel_selection_menu, window, view)
    if selected_kernel is not None:
        KernelManager.interrupt_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Interrupted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    continue_cb()


class HermesInterruptKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _interrupt_kernel(sublime.active_window(), self.view, logger=logger)


@chain_callbacks
def _restart_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    selected_kernel = yield partial(_show_kernel_selection_menu, window, view)
    if selected_kernel is not None:
        KernelManager.restart_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Restarted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    continue_cb()


class HermesRestartKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _restart_kernel(sublime.active_window(), self.view, logger=logger)


@chain_callbacks
def _shutdown_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    selected_kernel = yield partial(_show_kernel_selection_menu, window, view)
    if selected_kernel is not None:
        KernelManager.shutdown_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Shutdown kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    continue_cb()


class HermesShutdownKernel(TextCommand):
    """Set url of jupyter process."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _shutdown_kernel(sublime.active_window(), self.view, logger=logger)


def get_line(view: sublime.View, row: int) -> str:
    """Get the code line under the cursor."""
    point = view.text_point(row, 0)
    line_region = view.line(point)
    return view.substr(line_region)


def get_indent(view: sublime.View, row: int) -> str:
    line = get_line(view, row)
    return INDENT_PATTERN.match(line).group()


def get_block(view: sublime.View, s: sublime.Region) -> (str, sublime.Region):
    """Get the code block under the cursor.

    The code block is the lines satisfying the following conditions:

      - Includes the line under the cursor.
      - Includes no blank line.
      - More indented than that of the line under the cursor.

    If `s` is a selected region, the code block is it.
    """
    if not s.empty():
        return view.substr(s)
    view_end_row = view.rowcol(view.size())[0]
    current_row = view.rowcol(s.begin())[0]
    current_indent = get_indent(view, current_row)
    start_point = 0
    for first_row in range(current_row, -1, -1):
        indent = get_indent(view, first_row)
        if (not indent.startswith(current_indent) or get_line(view, first_row).strip() == ''):
            start_point = view.text_point(first_row + 1, 0)
            break
    end_point = view.size()
    for last_row in range(current_row, view_end_row + 1):
        indent = get_indent(view, last_row)
        if (not indent.startswith(current_indent) or get_line(view, last_row).strip() == ''):
            end_point = view.text_point(last_row, 0) - 1
            break
    block_region = sublime.Region(start_point, end_point)
    return (view.substr(block_region), block_region)


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
        code, _ = get_block(view, s)
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


def _set_status_updater(view):
    buffer_id = view.buffer_id()
    if buffer_id != sublime.active_window().active_view().buffer_id():
        return
    try:
        kernel = ViewManager.get_kernel_for_view(buffer_id)
        status = "[{lang}] {kernel_id} ({execution_state})".format(
            lang=kernel.lang,
            kernel_id=kernel.kernel_id,
            execution_state=kernel.execution_state)
        view.set_status("hermes_connected_kernel", status)
        sublime.set_timeout_async(lambda: _set_status_updater(view), 500)
    except KeyError:
        # When view is not connected.
        view.set_status("hermes_connected_kernel", "")
        return


class HermesStatusUpdater(ViewEventListener):
    """Listen to the heartbeat of kernel and update status of view."""

    def on_activated_async(self):
        _set_status_updater(self.view)


class HermesGetObjectInspection(TextCommand):
    """Get object inspection."""

    @chain_callbacks
    def run(self, edit, *, logger=HERMES_LOGGER):
        view = self.view
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
            code, region = get_block(view, s)
            cursor_pos = s.end() - region.begin()
            if code == pre_code:
                continue
            kernel.get_inspection(code, cursor_pos)
            log_info_msg = "Requested object inspection for code {code} with kernel {kernel_id}".format(
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
        use_complete = (
            sublime
            .load_settings("Hermes.sublime-settings")
            .get("complete")
        )
        if not use_complete:
            return None
        timeout = (
            sublime
            .load_settings("Hermes.sublime-settings")
            .get("complete_timeout")
        )
        try:
            kernel = ViewManager.get_kernel_for_view(view.buffer_id())
            location = locations[0]
            code = view.substr(view.line(location))
            _, col = view.rowcol(location)
            return [
                (completion + "\tHermes", completion)
                for completion
                in kernel.get_complete(code, col, timeout)]
        except (KeyError, WebSocketTimeoutException):
            return None
