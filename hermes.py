"""Hermes package for Sublime Text 3.

The package provides code execution and completion in interaction with Jupyter.
Copyright (c) 2016-2017, NEGORO Tetsuya (https://github.com/ngr-t)
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

from .utils import chain_callbacks

import bisect

# Logger setting
HERMES_LOGGER = getLogger(__name__)
HANDLER = StreamHandler()
HANDLER.setLevel(INFO)

if len(HERMES_LOGGER.handlers) == 0:
    HERMES_LOGGER.setLevel(INFO)
    HERMES_LOGGER.addHandler(HANDLER)

# Regex patterns to extract code lines.
INDENT_PATTERN = re.compile(r"^([ \t]*)")

# Regex pattern to find code cell blocks delimiters
# #%%
# # %%
# # <codecell>
CELL_DELIMITER_PATTERN = r"^(#\s?%%)|(# <codecell>)\s*$"

# TODO: move CSS into separate file
RUN_CELL_PHANTOM = """<body id="hermes-runCell">
  <style>
    .runCell {
        text-decoration: none;
        color: color(var(--bluish) alpha(0.33));
        font-style: italic;
    }
  </style>
  <a class='runCell' href='runCell'>Run cell</a>
</body>
"""

RUN_CELL_PHANTOM_ID = "HermesRunCell"


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
    def remove_view(cls, buffer_id):
        """Remove view from manager."""
        if buffer_id in cls.view_kernel_table:
            del cls.view_kernel_table[buffer_id]

    @classmethod
    def get_kernel_for_view(cls, buffer_id) -> KernelConnection:
        """Get Kernel instance corresponding to the buffer_id."""
        return cls.view_kernel_table[buffer_id]


class KernelManager(object):
    """Manage Jupyter kernels."""

    # type: Dict[Tuple[str, str], KernelConnection]
    # The key is a tuple consisted of the name of kernelspec and kernel ID,
    # the value is a KernelConnection instance correspond to it.
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
    def get_kernel(cls, kernelspec_name, kernel_id, connection_name=None):
        """Get KernelConnection object."""
        if (kernelspec_name, kernel_id) in cls.kernels:
            return cls.kernels[(kernelspec_name, kernel_id)]
        else:
            if cls._token:
                kernel = KernelConnection(
                    kernelspec_name,
                    kernel_id,
                    cls,
                    auth_type="token",
                    token=cls._token,
                    connection_name=connection_name,
                    logger=HERMES_LOGGER)
            else:
                kernel = KernelConnection(
                    kernelspec_name,
                    kernel_id,
                    cls,
                    connection_name=connection_name,
                    logger=HERMES_LOGGER)
            cls.kernels[(kernelspec_name, kernel_id)] = kernel
            return kernel

    @classmethod
    def start_kernel(cls, kernelspec_name, connection_name=None):
        """Start kernel and return a `Kernel` instance."""
        url = '{}/api/kernels'.format(cls.base_url())
        data = dict(name=kernelspec_name)
        response = cls.post_request(
            url,
            data=json.dumps(data))
        return cls.get_kernel(response["name"], response["id"], connection_name=connection_name)

    @classmethod
    def shutdown_kernel(cls, kernel_id):
        """Shutdown kernel."""
        url = '{base_url}/api/kernels/{kernel_id}'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        name, = [name for name, i in cls.kernels if i == kernel_id]
        del cls.kernels[(name, kernel_id)]
        cls.delete_request(url)

    @classmethod
    def restart_kernel(cls, kernel_id):
        """Restart kernel."""
        url = '{base_url}/api/kernels/{kernel_id}/restart'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        cls.post_request(url, dict())

    @classmethod
    def interrupt_kernel(cls, kernel_id):
        """Interrupt kernel."""
        url = '{base_url}/api/kernels/{kernel_id}/interrupt'.format(
            base_url=cls.base_url(),
            kernel_id=kernel_id)
        cls.post_request(url, dict())

    @classmethod
    def post_request(cls, url, data) -> dict:
        """Send a POST HTTP request to the `url` with `data` as a body and get response."""
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
        if response.status_code != requests.codes.ok:
            response.raise_for_status()
        return response.json()

    @classmethod
    def get_request(cls, url) -> dict:
        """Send a GET HTTP request to the `url` and get response."""
        if cls._token:
            header_auth_body = "token {token}".format(
                token=cls._token)
            header = dict(Authorization=header_auth_body)
        else:
            header = dict()
        response = requests.get(
            url,
            headers=header)
        if response.status_code != requests.codes.ok:
            response.raise_for_status()
        return response.json()

    @classmethod
    def delete_request(cls, url) -> dict:
        """Send a DELETE HTTP request to the `url`."""
        if cls._token:
            header_auth_body = "token {token}".format(
                token=cls._token)
            header = dict(Authorization=header_auth_body)
        else:
            header = dict()
        response = requests.delete(
            url,
            headers=header)
        if response.status_code != requests.codes.ok:
            response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return


@chain_callbacks
def _connect_server(window, *, continue_cb=lambda: None):
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


class HermesConnectServer(WindowCommand):
    """Set url of jupyter process."""

    def run(self):
        """Command."""
        _connect_server(self.window)


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
        yield partial(_connect_server, window)

    menu_items = list(kernelspecs["kernelspecs"].keys())

    index = yield partial(
        window.show_quick_panel,
        menu_items)

    if index == -1:
        return
    selected_kernelspec = menu_items[index]
    connection_name = yield partial(window.show_input_panel, "connection name", "", on_change=None, on_cancel=None)
    if connection_name == "":
        connection_name = None
    kernel = KernelManager.start_kernel(selected_kernelspec, connection_name=connection_name)
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
        conn = KernelManager.get_kernel(selected_kernel["name"], selected_kernel["id"])
        curr_name = conn.connection_name if conn.connection_name is not None else ""
        new_name = yield partial(window.show_input_panel, "New name", curr_name, on_change=None, on_cancel=None)
        conn.connection_name = new_name
    elif subcommands[index] is sc.interrupt:
        # Interrupt
        KernelManager.interrupt_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Interrupted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    elif subcommands[index] is sc.restart:
        # Restart
        KernelManager.restart_kernel(
            selected_kernel["id"])
        log_info_msg = (
            "Restarted kernel {kernel_id}.").format(
            kernel_id=selected_kernel["id"])
        logger.info(log_info_msg)
    elif subcommands[index] is sc.shutdown:
        # Shutdown
        KernelManager.shutdown_kernel(
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
    try:
        kernel_list = KernelManager.list_kernels()
    except (requests.RequestException, AttributeError):
        sublime.message_dialog("Set URL first, please.")
        yield lambda cb: _connect_server(window, continue_cb=cb)
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

        update_run_cell_phantoms(view)

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

    # It's better to pass the list of (connection_name, kernel_id) tuples to improve the appearane of the menu.
    try:
        kernel_list = KernelManager.list_kernels()
    except (requests.RequestException, AttributeError):
        sublime.message_dialog("Connect to Jupyter first, please.")
        yield lambda cb: _connect_server(window, continue_cb=cb)
        kernel_list = KernelManager.list_kernels()
    menu_items = [
        "* " + repr if kernel["id"] == current_kernel_id else repr
        for repr, kernel
        in zip(KernelManager.list_kernel_reprs(), kernel_list)
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
        KernelManager.interrupt_kernel(
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
        return kernel.is_alive()

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
        KernelManager.restart_kernel(
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
        return kernel.is_alive()

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
        KernelManager.shutdown_kernel(
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
        return kernel.is_alive()

    def is_visible(self, *, logger=HERMES_LOGGER):
        return self.is_enabled()

    def run(self, edit, *, logger=HERMES_LOGGER):
        """Command definition."""
        _shutdown_kernel(sublime.active_window(), self.view, logger=logger)


class HermesRunCellManager(ViewEventListener):
    """Manage 'Run cell' phantoms"""

    def __init__(self, view):
        self.view = view
        self.timeout_scheduled = False
        self.needs_update = False

    def on_modified(self, *, logger=HERMES_LOGGER):
        try:
            ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return

        # Call update_run_cell_phantoms(), but not any more than 10 times a second
        if self.timeout_scheduled:
            self.needs_update = True
        else:
            sublime.set_timeout(lambda: self.handle_timeout(), 100)
            self.timeout_scheduled = True
            update_run_cell_phantoms(self.view, logger=logger)

    def handle_timeout(self):
        self.timeout_scheduled = False
        if self.needs_update:
            self.needs_update = False
            update_run_cell_phantoms(self.view)


def update_run_cell_phantoms(view, *, logger=HERMES_LOGGER):
    """Add "Run Cell" links to each code cell"""

    # find all cell delimiters:
    limits = view.find_all(CELL_DELIMITER_PATTERN)
    # append a virtual delimiter at EOF
    limits.append(sublime.Region(view.size(), view.size()))

    # remove existing Run cell phantoms, we'll recreate all of them
    view.erase_phantoms(RUN_CELL_PHANTOM_ID)

    for i in range(len(limits) - 1):
        code_region = sublime.Region(limits[i].end() + 1, limits[i+1].begin() - 1)
        phantom_region = sublime.Region(limits[i].end(), limits[i].end())
        view.add_phantom(
            RUN_CELL_PHANTOM_ID,
            phantom_region,
            RUN_CELL_PHANTOM,
            sublime.LAYOUT_INLINE,
            on_navigate=lambda href, view=view, region=code_region: _execute_cell(view, region))


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


def get_cell(view: sublime.View, region: sublime.Region, *, logger=HERMES_LOGGER) -> (str, sublime.Region):
    """Get the code cell under the cursor.

    Cells are separated by markers defined in CELL_DELIMITER_PATTERN:
        #%%
        # %%
        # <codecell>

    If `s` is a selected region, the code cell is it.
    """
    if not region.empty():
        return (view.substr(region), region)
    separators = view.find_all(CELL_DELIMITER_PATTERN)
    start_point = separators[bisect.bisect(separators, region)-1].end() + 1
    end_point = separators[bisect.bisect(separators, region)].begin() - 1
    cell_region = sublime.Region(start_point, end_point)
    return (view.substr(cell_region), cell_region)


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
        code, region = get_cell(view, s, logger=logger)
        if code == pre_code:
            continue
        kernel.execute_code(code, region)
        log_info_msg = "Executed code {code} with kernel {kernel_id}".format(
            code=code,
            kernel_id=kernel.kernel_id)
        logger.info(log_info_msg)
        pre_code = code


@chain_callbacks
def _execute_cell(view, cell: sublime.Region, *, logger=HERMES_LOGGER):
    try:
        kernel = ViewManager.get_kernel_for_view(view.buffer_id())
    except KeyError:
        sublime.message_dialog("No kernel is connected to this view.")
        yield lambda cb: _connect_kernel(
            sublime.active_window(),
            view,
            continue_cb=cb)
        kernel = ViewManager.get_kernel_for_view(view.buffer_id())

    code = view.substr(cell)
    kernel.execute_code(code, cell)
    log_info_msg = "Executed code {code} with kernel {kernel_id}".format(
        code=code,
        kernel_id=kernel.kernel_id)
    logger.info(log_info_msg)


class HermesExecuteBlock(TextCommand):
    """Execute code."""

    def is_enabled(self, *, logger=HERMES_LOGGER):
        try:
            kernel = ViewManager.get_kernel_for_view(self.view.buffer_id())
        except KeyError:
            return False
        return kernel.is_alive()

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
        return kernel.is_alive()

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
            _, col = view.rowcol(location)
            return [
                (completion + "\tHermes", completion)
                for completion
                in kernel.get_complete(code, col, timeout)]
        except Exception:
            return None
