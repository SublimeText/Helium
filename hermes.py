"""Hermes package for Sublime Text 3.

The package provides code execution and completion in interaction with Jupyter.

Copyright (c) 2016-2018, NEGORO Tetsuya (https://github.com/ngr-t)
"""

import json
import os
import re
import uuid
from functools import partial
from logging import getLogger, INFO, StreamHandler


import sublime
from sublime_plugin import (
    TextCommand,
    EventListener,
    ViewEventListener
)
from .kernel import KernelConnection

from .utils import add_path, chain_callbacks

with add_path(os.path.join(os.path.dirname(__file__), "lib")):
    # Import jupyter_client related functions and classes.
    # Temporarily insert `lib` into sys.path not to affect other packages.
    from jupyter_client.connect import tunnel_to_kernel
    from jupyter_client.kernelspec import find_kernel_specs
    from jupyter_client.manager import KernelManager

# Logger setting
HERMES_LOGGER = getLogger(__name__)
HANDLER = StreamHandler()
HANDLER.setLevel(INFO)

if len(HERMES_LOGGER.handlers) == 0:
    HERMES_LOGGER.setLevel(INFO)
    HERMES_LOGGER.addHandler(HANDLER)

# Regex patterns to extract code lines.
INDENT_PATTERN = re.compile(r"^([ \t]*)")


ORG_JUPYTER_PATH = os.environ.get('JUPYTER_PATH')


def _refresh_jupyter_path():
    additional_jupyter_path = sublime.load_settings("Hermes.sublime-settings").get('jupyter_path')
    os.environ['JUPYTER_PATH'] = ':'.join([
        path
        for path
        in [ORG_JUPYTER_PATH, additional_jupyter_path]
        if path is not None
    ])


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
        kernel = HermesKernelManager.get_kernel(kernel_id)
        cls.view_kernel_table[buffer_id] = kernel
        inline_output = (
            sublime
            .load_settings("Hermes.sublime-settings")
            .get("inline_output"))
        if not inline_output:
            kernel.activate_view()

    @classmethod
    def remove_view(cls, buffer_id):
        """Remove view from manager."""
        if buffer_id in cls.view_kernel_table:
            del cls.view_kernel_table[buffer_id]

    @classmethod
    def get_kernel_for_view(cls, buffer_id) -> KernelConnection:
        """Get Kernel instance corresponding to the buffer_id."""
        return cls.view_kernel_table[buffer_id]


class HermesKernelManager(object):
    """Manage Jupyter kernels."""

    # type: Dict[Tuple[str, str], KernelConnection]
    # The key is a tuple consisted of the name of kernelspec and kernel ID,
    # the value is a KernelConnection instance correspond to it.
    kernels = dict()
    logger = HERMES_LOGGER

    def __new__(cls, *args, **kwargs):
        """Make this class a singleton."""
        if not hasattr(cls, "__instance__"):
            cls.__instance__ = super(HermesKernelManager, object).__new__(
                cls, *args, **kwargs)
        return cls.__instance__

    @classmethod
    def list_kernelspecs(cls):
        """Get the kernelspecs."""
        _refresh_jupyter_path()
        return find_kernel_specs()

    @classmethod
    def list_kernels(cls):
        """Get the list of kernels."""
        return [
            {'name': cls.get_kernel(kernel_id).lang,
             'id': kernel_id}
            for kernel_id
            in cls.kernels.keys()
            if cls.get_kernel(kernel_id).is_alive()
        ]

    @classmethod
    def list_kernel_reprs(cls):
        """Get the list of representations of kernels."""
        def get_repr(kernel):
            key = (kernel["name"], kernel["id"])
            try:
                return cls.kernels[key].repr
            except KeyError:
                return "[{lang}] {kernel_id}".format(
                    lang=kernel["name"],
                    kernel_id=kernel["id"])
        return list(map(get_repr, cls.list_kernels()))

    @classmethod
    def get_kernel(cls, kernel_id, connection_name=None):
        """Get KernelConnection object."""
        return cls.kernels[kernel_id]

    @classmethod
    def start_kernel(
        cls,
        kernelspec_name=None,
        connection_info=None,
        connection_name=None,
    ):
        """Start kernel and return a `Kernel` instance."""
        kernel_id = uuid.uuid4()
        if kernelspec_name:
            kernel_manager = KernelManager(kernel_name=kernelspec_name)
            kernel_manager.start_kernel()
        elif connection_info:
            kernel_manager = KernelManager()
            kernel_manager.load_connection_info(connection_info)
            # `KernelManager.kernel_name` is not automatically set from connection info.
            kernel_manager.kernel_name = connection_info.get("kernel_name", "")
        else:
            raise Exception(
                "You must specify any of {`kernelspec_name`, `connection_info`}.")
        kernel = KernelConnection(
            kernel_id,
            kernel_manager,
            cls,
            connection_name=connection_name,
            logger=cls.logger
        )
        cls.kernels[kernel_id] = kernel
        return kernel

    @classmethod
    def shutdown_kernel(cls, kernel_id):
        """Shutdown kernel."""
        cls.get_kernel(kernel_id).shutdown_kernel()

    @classmethod
    def restart_kernel(cls, kernel_id):
        """Restart kernel."""
        cls.get_kernel(kernel_id).shutdown_kernel(restart=True)

    @classmethod
    def interrupt_kernel(cls, kernel_id):
        """Interrupt kernel."""
        cls.get_kernel(kernel_id).interrupt_kernel()


@chain_callbacks
def _enter_connection_info(window, continue_cb):
    connection_info_str = yield partial(
        window.show_input_panel,
        "Enter connection info or the path to connection file.", "", on_change=None, on_cancel=None)
    try:
        continue_cb(json.loads(connection_info_str))
    except ValueError:
        try:
            with open(connection_info_str) as infs:
                continue_cb(json.loads(infs.read()))
        except FileNotFoundError:
            sublime.message_dialog(
                'The input string was neither a valid JSON string nor a file path.')
            raise


@chain_callbacks
def _start_kernel(
    window,
    view,
    continue_cb=lambda: None,
    *,
    logger=HERMES_LOGGER
):
    kernelspecs = HermesKernelManager.list_kernelspecs()
    menu_items = list(kernelspecs.keys()) + [
        "(Enter connection info)",
        "(Connect remote kernel via SSH)"
    ]
    index = yield partial(
        window.show_quick_panel,
        menu_items)

    if index == -1:
        return
    elif index == len(kernelspecs):
        # Create a kernel from connection info.
        connection_info = yield partial(_enter_connection_info, window)
        connection_name = yield partial(
            window.show_input_panel, "connection name", "", on_change=None, on_cancel=None)
        if connection_name == "":
            connection_name = None
        kernel = HermesKernelManager.start_kernel(
            connection_info=connection_info,
            connection_name=connection_name
        )
    elif index == len(kernelspecs) + 1:
        # Create a kernel with SSH tunneling.
        servers = (
            sublime
            .load_settings('Hermes.sublime-settings')
            .get('ssh_servers')
        )
        if not servers:
            sublime.message_dialog(
                'Please set `ssh_servers` item of the config file via `Hermes: Settings` to connect SSH servers.')
            return
        menu_items = list(servers.keys())
        server_index = yield partial(
            window.show_quick_panel,
            menu_items)
        server = servers[menu_items[server_index]]
        connection_info = yield partial(_enter_connection_info, window)
        shell_port, iopub_port, stdin_port, hb_port = tunnel_to_kernel(
            connection_info, server['server'], server.get('key', None))
        new_ports = {
            'shell_port': shell_port,
            'iopub_port': iopub_port,
            'stdin_port': stdin_port,
            'hb_port': hb_port,
        }
        connection_info.update(new_ports)
        connection_name = yield partial(
            window.show_input_panel, "connection name", "", on_change=None, on_cancel=None)
        kernel = HermesKernelManager.start_kernel(
            connection_info=connection_info,
            connection_name=connection_name
        )
    else:
        # Create a kernel from the kernelspec name.
        selected_kernelspec = menu_items[index]
        connection_name = yield partial(
            window.show_input_panel, "connection name", "", on_change=None, on_cancel=None)
        if connection_name == "":
            connection_name = None
        kernel = HermesKernelManager.start_kernel(
            kernelspec_name=selected_kernelspec,
            connection_name=connection_name
        )
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


class ListKernelsSubcommands(object):

    connect = "Connect"
    rename = "Rename"
    interrupt = "Interrupt"
    restart = "Restart"
    shutdown = "Shutdown"
    back = "Back to the kernel list"


@chain_callbacks
def _list_kernels(window, view, *, logger=HERMES_LOGGER):
    sc = ListKernelsSubcommands
    selected_kernel = yield partial(_show_kernel_selection_menu, window, view, add_new=True)
    subcommands = [sc.connect, sc.rename, sc.interrupt, sc.restart, sc.shutdown, sc.back]
    try:
        if selected_kernel["id"] == ViewManager.get_kernel_for_view(view.buffer_id()).kernel_id:
            subcommands = [sc.rename, sc.interrupt, sc.restart, sc.shutdown, sc.back]
    except KeyError:
        # No kernel is connected
        # `subcommands` includes "Connect"
        pass
    index = yield partial(window.show_quick_panel, subcommands)
    if index == -1:
        return
    elif subcommands[index] is sc.connect:
        # Connect
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
    elif subcommands[index] is sc.rename:
        # Rename
        conn = HermesKernelManager.get_kernel(selected_kernel["id"])
        curr_name = conn.connection_name if conn.connection_name is not None else ""
        new_name = yield partial(window.show_input_panel, "New name", curr_name, on_change=None, on_cancel=None)
        conn.connection_name = new_name
    elif subcommands[index] is sc.interrupt:
        # Interrupt
        HermesKernelManager.interrupt_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Interrupted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    elif subcommands[index] is sc.restart:
        # Restart
        HermesKernelManager.restart_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Restarted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    elif subcommands[index] is sc.shutdown:
        # Shutdown
        HermesKernelManager.shutdown_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Shutdown kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    elif subcommands[index] is sc.back:
        # Back to the kernel list
        yield _list_kernels(window, view)
    sublime.set_timeout_async(lambda: StatusBar(view), 0)


class HermesListKernels(TextCommand):
    """Command that shows the list of kernels and do some action for chosen kernels."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        _list_kernels(sublime.active_window(), self.view)


@chain_callbacks
def _connect_kernel(
    window,
    view,
    *,
    continue_cb=lambda: None,
    logger=HERMES_LOGGER
):
    kernel_list = HermesKernelManager.list_kernels()
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
    sublime.set_timeout_async(lambda: StatusBar(view), 0)
    continue_cb()


class HermesConnectKernel(TextCommand):
    """Connect to jupyter kernel."""

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _connect_kernel(sublime.active_window(), self.view, logger=logger)


@chain_callbacks
def _show_kernel_selection_menu(window, view, cb, *, add_new=False):
    # Get the kurnel ID related to `view` if exists.
    try:
        current_kernel_id = ViewManager.get_kernel_for_view(view.buffer_id()).kernel_id
    except KeyError:
        # TODO fix to use property of views.
        result = re.match(r"\*Hermes Output\* .*?\(\[.*?\] ([\w-]*)\)", view.name())
        if result:
            current_kernel_id = result.group(1)
        else:
            current_kernel_id = ""

    # It's better to pass the list of (connection_name, kernel_id) tuples
    # to improve the appearane of the menu.
    kernel_list = HermesKernelManager.list_kernels()
    menu_items = [
        "* " + repr if kernel["id"] == current_kernel_id else repr
        for repr, kernel
        in zip(HermesKernelManager.list_kernel_reprs(), kernel_list)
    ]
    if add_new:
        menu_items += ["New kernel"]
    index = yield partial(
        window.show_quick_panel,
        menu_items)
    if index == -1:
        selected_kernel = None
    elif index == len(kernel_list):
        yield partial(_start_kernel, window, view)
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
        HermesKernelManager.interrupt_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Interrupted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    continue_cb()


class HermesInterruptKernel(TextCommand):
    """Interrupt jupyter kernel."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return HermesKernelManager.get_kernel(kernel.kernel_id).is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

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
        HermesKernelManager.restart_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Restarted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    continue_cb()


class HermesRestartKernel(TextCommand):
    """Restart jupyter kernel."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return HermesKernelManager.get_kernel(kernel.kernel_id).is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

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
        HermesKernelManager.shutdown_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Shutdown kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    ViewManager.remove_view(view.buffer_id())
    view.set_status("hermes_connected_kernel", '')
    continue_cb()


class HermesShutdownKernel(TextCommand):
    """Shutdown jupyter kernel."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return HermesKernelManager.get_kernel(kernel.kernel_id).is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

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
        return (view.substr(s), s)
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
        code, region = get_block(view, s)
        if code == pre_code:
            continue
        kernel.execute_code(code, region, view)
        log_info_msg = "Executed code {code} with kernel {kernel_id}".format(
            code=code,
            kernel_id=kernel.kernel_id)
        logger.info(log_info_msg)
        pre_code = code


class HermesExecuteBlock(TextCommand):
    """Execute code."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return HermesKernelManager.get_kernel(kernel.kernel_id).is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _execute_block(self.view, logger=logger)


class StatusBar(object):
    """Status Bar with animation."""
    # This class is based on the one by @randy3k.

    def __init__(self, view, width=10, interval=500):
        self.view = view
        self.width = width
        self.buffer_id = view.buffer_id()
        self.interval = interval
        self.pos = 0
        try:
            self.kernel = ViewManager.get_kernel_for_view(self.buffer_id)
            self.start()
        except KeyError:
            # When view is not connected.
            self.stop()

    def start(self):
        self.update()

    def stop(self):
        self.view.set_status("hermes_connected_kernel", "")

    def update(self, pos=0):
        # `pos` can't be a property of `StatusBar` because it's not updated
        # when `update()` is called by `sublime.set_timeout[_async]()`.
        if self.buffer_id != sublime.active_window().active_view().buffer_id():
            # Stop when view is unfocused.
            self.stop()
            return
        execution_state = self.kernel.execution_state
        if execution_state == "dead":
            # Stop when kernel is dead.
            self.view.set_status("hermes_connected_kernel", '')
            return
        elif execution_state == "busy":
            pos = pos % (2 * self.width)
            before = min(pos, (2 * self.width) - pos)
            after = self.width - before
            progress_bar = " [{}={}]".format(" " * before, " " * after)
        else:
            # Make progress bar always start with pos=0.
            pos = -1
            progress_bar = ""
        status = "{repr} (state: {execution_state})".format(
            repr=self.kernel.repr,
            execution_state=self.kernel.execution_state) + progress_bar
        self.view.set_status("hermes_connected_kernel", status)
        sublime.set_timeout_async(lambda: self.update(pos + 1), self.interval)


class HermesStatusUpdater(ViewEventListener):
    """Listen to the heartbeat of kernel and update status of view."""

    def on_activated_async(self):
        sublime.set_timeout_async(lambda: StatusBar(self.view), 0)


class HermesGetObjectInspection(TextCommand):
    """Get object inspection."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return HermesKernelManager.get_kernel(kernel.kernel_id).is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

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
            log_info_msg = "Requested completion for code {code} with kernel {kernel_id}".format(
                code=code,
                kernel_id=kernel.kernel_id)
            logger.info(log_info_msg)
            _, col = view.rowcol(location)
            return kernel.get_complete(code, col, timeout)
        except Exception:
            return None
