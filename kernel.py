"""Definition of KernelConnection class.

KernelConnection class provides interaction with Jupyter kernels.

Copyright (c) 2017-2018, NEGORO Tetsuya (https://github.com/ngr-t)
"""
import re
from collections import defaultdict
from threading import Thread, RLock
from queue import Empty, Queue

import sublime

from .utils import (
    show_password_input,
)


JUPYTER_PROTOCOL_VERSION = '5.0'

REPLY_STATUS_OK = "ok"
REPLY_STATUS_ERROR = "error"
REPLY_STATUS_ABORT = "abort"

MSG_TYPE_EXECUTE_INPUT = 'execute_input'
MSG_TYPE_EXECUTE_REQUEST = 'execute_request'
MSG_TYPE_EXECUTE_RESULT = 'execute_result'
MSG_TYPE_EXECUTE_REPLY = 'execute_reply'
MSG_TYPE_COMPLETE_REQUEST = 'complete_request'
MSG_TYPE_COMPLETE_REPLY = 'complete_reply'
MSG_TYPE_DISPLAY_DATA = 'display_data'
MSG_TYPE_INSPECT_REQUEST = "inspect_request"
MSG_TYPE_INSPECT_REPLY = "inspect_reply"
MSG_TYPE_INPUT_REQUEST = "input_request"
MSG_TYPE_INPUT_REPLY = "input_reply"
MSG_TYPE_ERROR = 'error'
MSG_TYPE_STREAM = 'stream'
MSG_TYPE_STATUS = 'status'

HERMES_FIGURE_PHANTOMS = "hermes_figure_phantoms"

# Used as key of status bar.
KERNEL_STATUS_KEY = "hermes_kernel_status"

HERMES_OBJECT_INSPECT_PANEL = "hermes_object_inspect"

ANSI_ESCAPE_PATTERN = re.compile(r'\x1b[^m]*m')

OUTPUT_VIEW_SEPARATOR = "-" * 80


def extract_content(messages, msg_type):
    """Extract content from messages received from a kernel."""
    return [
        message['content']
        for message
        in messages
        if message['header']['msg_type'] == msg_type]


def remove_ansi_escape(text: str):
    return ANSI_ESCAPE_PATTERN.sub('', text)


def get_msg_type(message):
    return message['header']['msg_type']


def extract_data(result):
    """Extract plain text data."""
    try:
        return result['data']
    except KeyError:
        return ""


class KernelConnection(object):
    """Interact with a Jupyter kernel."""

    class ShellMessageReceiver(Thread):
        """Communicator that runs asynchroniously."""

        def __init__(self, kernel):
            """Initialize AsyncCommunicator class."""
            super().__init__()
            self._kernel = kernel

        def run(self):
            """Main routine."""
            # TODO: log
            while True:
                try:
                    msg = self._kernel.client.get_shell_msg()
                    self._kernel.shell_msg_queues_lock.acquire()
                    try:
                        queue = self._kernel.shell_msg_queues[msg['parent_header']['msg_id']]
                    finally:
                        self._kernel.shell_msg_queues_lock.release()
                    queue.put(msg)
                except Exception as ex:
                    self._kernel._logger.exception(ex)

    class IOPubMessageReceiver(Thread):
        """Receive and process IOPub messages."""

        def __init__(self, kernel):
            super().__init__()
            self._kernel = kernel

        def run(self):
            """Main routine."""
            # TODO: log, handle other message types.
            while True:
                try:
                    msg = self._kernel.client.get_iopub_msg()
                    self._kernel._logger.info(msg)
                    content = msg.get("content", dict())
                    execution_count = content.get("execution_count", None)
                    msg_type = msg['msg_type']
                    if msg_type == MSG_TYPE_STATUS:
                        self._kernel._execution_state = content['execution_state']
                    elif msg_type == MSG_TYPE_EXECUTE_INPUT:
                        self._kernel._write_text_to_view("\n\n" + OUTPUT_VIEW_SEPARATOR + "\n\n")
                        self._kernel._output_input_code(content['code'], content['execution_count'])
                    elif msg_type == MSG_TYPE_ERROR:
                        self._kernel._logger.info("Handling error")
                        self._kernel._handle_error(
                            execution_count,
                            content["ename"],
                            content["evalue"],
                            content["traceback"],
                        )
                    elif msg_type == MSG_TYPE_DISPLAY_DATA:
                        self._kernel._write_mime_data_to_view(content["data"])
                    elif msg_type == MSG_TYPE_EXECUTE_RESULT:
                        self._kernel._write_mime_data_to_view(content["data"])
                    elif msg_type == MSG_TYPE_STREAM:
                        self._kernel._handle_stream(content["name"], content["text"])
                except Exception as ex:
                    self._kernel._logger.exception(ex)

    class StdInMessageReceiver(Thread):
        """Receive and process IOPub messages."""

        def __init__(self, kernel):
            super().__init__()
            self._kernel = kernel

        def _handle_input_request(self, prompt, password):
            def interrupt():
                self.manager.interrupt_kernel(self.kernel_id)

            if password:
                show_password_input(prompt, self._kernel.input, interrupt)
            else:
                (sublime
                 .active_window()
                 .show_input_panel(
                     prompt,
                     "",
                     self._kernel.client.input,
                     lambda x: None,
                     interrupt
                 ))

        def run(self):
            """Main routine."""
            # TODO: log, handle other message types.
            while True:
                try:
                    msg = self._kernel.client.get_stdin_msg()
                    msg_type = msg['msg_type']
                    content = msg['content']
                    if msg_type == MSG_TYPE_INPUT_REQUEST:
                        self._handle_input_request(content["prompt"], content["password"])
                except Exception as ex:
                    self._kernel._logger.exception(ex)

    def __init__(
        self,
        kernel_id,
        manager,
        connection_name=None,
        logger=None,
    ):
        """Initialize KernelConnection class.

        paramters
        ---------
        kernel_id str: kernel ID
        manager parent kernel manager
        """
        self._logger = logger
        self.shell_msg_queues = defaultdict(Queue)
        self._kernel_id = kernel_id
        self.manager = manager
        self.kernel_manager = manager.multi_kernel_manager.get_kernel(kernel_id)
        self.client = self.kernel_manager.client()
        self.shell_msg_queues_lock = RLock()
        self._connection_name = connection_name
        self._execution_state = 'unknown'
        # Set the attributes refered by receivers before they start.
        self._shell_msg_receiver = self.ShellMessageReceiver(self)
        self._shell_msg_receiver.start()
        self._iopub_msg_receiver = self.IOPubMessageReceiver(self)
        self._iopub_msg_receiver.start()
        self._stdin_msg_receiver = self.StdInMessageReceiver(self)
        self._stdin_msg_receiver.start()

    @property
    def lang(self):
        """Language of kernel."""
        return self.kernel_manager.kernel_name

    @property
    def kernel_id(self):
        """ID of kernel."""
        return self._kernel_id

    def get_connection_name(self):
        return self._connection_name

    def set_connection_name(self, new_name):
        # We also have to change the view name now.
        view = self.get_view()
        self._connection_name = new_name
        view.set_name(self.view_name)

    def del_connection_name(self):
        self._connection_name = None

    connection_name = property(
        get_connection_name,
        set_connection_name,
        del_connection_name,
        "Name of kernel connection shown in a view title.")

    @property
    def view_name(self):
        """The name of output view."""
        return "*Hermes Output* {repr}".format(repr=self.repr)

    @property
    def repr(self):
        """A string used as the representation of the connection"""
        if self.connection_name:
            return "{connection_name} ([{lang}] {kernel_id})".format(
                connection_name=self.connection_name,
                lang=self.lang,
                kernel_id=self.kernel_id)
        else:
            return "[{lang}] {kernel_id}".format(
                lang=self.lang,
                kernel_id=self.kernel_id)

    @property
    def execution_state(self):
        return self._execution_state

    def activate_view(self):
        """Activate view to show the output of kernel."""
        view = self.get_view()
        current_view = sublime.active_window().active_view()
        sublime.active_window().focus_view(view)
        view.set_scratch(True)  # avoids prompting to save
        view.settings().set("word_wrap", "false")
        sublime.active_window().focus_view(current_view)

    def _output_input_code(self, code, execution_count):
        line = "In[{execution_count}]: {code}".format(
            execution_count=execution_count,
            code=code)
        self._write_text_to_view(line)

    def _handle_error(self, execution_count, ename, evalue, traceback) -> None:
        lines = "\nError[{execution_count}]: {ename}, {evalue}.\nTraceback:\n{traceback}".format(
            execution_count=execution_count,
            ename=ename,
            evalue=evalue,
            traceback="\n".join(traceback))
        self._write_text_to_view(remove_ansi_escape(lines))

    def _handle_stream(self, name, text) -> None:
        # Currently don't consider real time catching of streams.
        self._write_text_to_view("\n({name}):\n{text}".format(name, text))

    def _write_out_execution_count(self, execution_count) -> None:
        self._write_text_to_view("\nOut[{}]: ".format(execution_count))

    def _write_text_to_view(self, text: str) -> None:
        self.activate_view()
        view = self.get_view()
        view.set_read_only(False)
        view.run_command(
            'append',
            {'characters': text})
        view.set_read_only(True)
        view.show(view.size())

    def _write_phantom(self, content: str):
        file_size = self.get_view().size()
        region = sublime.Region(file_size, file_size)
        self.get_view().add_phantom(
            HERMES_FIGURE_PHANTOMS,
            region,
            content,
            sublime.LAYOUT_BLOCK)
        self._logger.info("Created phantom {}".format(content))

    def _write_mime_data_to_view(self, mime_data: dict) -> None:
        self.activate_view()
        if "text/plain" in mime_data:
            # Some kernel (such as IRkernel) sends text in display_data.
            result = mime_data["text/plain"]
            lines = "\n(display data): {result}".format(result=result)
            self._write_text_to_view(lines)
        elif "text/markdown" in mime_data:
            # Some kernel (such as IRkernel) sends text in display_data.
            result = mime_data["text/markdown"]
            lines = "\n(display data): {result}".format(result=result)
            self._write_text_to_view(lines)
        elif "text/html" in mime_data:
            # Some kernel (such as IRkernel) sends text in display_data.
            self._logger.info("Caught 'text/html' output without plain text. Try to show with phantom.")
            content = mime_data["text/html"]
            self._write_phantom(content)
        if "image/png" in mime_data:
            data = mime_data["image/png"]
            self._logger.info("Caught image.")
            content = (
                '<body style="background-color:white">' +
                '<img alt="Out" src="data:image/png;base64,{data}" />' +
                '</body>'
            ).format(
                data=data.strip(),
                bgcolor="white")
            self._write_phantom(content)

    def _handle_inspect_reply(self, reply: dict):
        window = sublime.active_window()
        if window.find_output_panel(HERMES_OBJECT_INSPECT_PANEL) is not None:
            window.destroy_output_panel(HERMES_OBJECT_INSPECT_PANEL)
        view = window.create_output_panel(HERMES_OBJECT_INSPECT_PANEL)
        try:
            self._logger.debug(reply)
            text = remove_ansi_escape(reply["text/plain"])
            view.run_command(
                'append',
                {'characters': text})
            window.run_command(
                'show_panel',
                dict(panel="output." + HERMES_OBJECT_INSPECT_PANEL))
        except KeyError as ex:
            self._logger.exception(ex)

    def get_view(self):
        """Get view corresponds to the KernelConnection."""
        view = None
        view_name = self.view_name
        views = sublime.active_window().views()
        for view_candidate in views:
            if view_candidate.name() == view_name:
                return view_candidate
        if not view:
            view = sublime.active_window().new_file()
            view.set_name(view_name)
            return view

    def execute_code(self, code):
        """Run code with Jupyter kernel."""
        msg_id = self.client.execute(code)
        info_message = "Kernel executed code ```{code}```.".format(code=code)
        self._logger.info(info_message)

    def is_alive(self):
        """Return True if kernel is alive."""
        return self.kernel_manager.is_alive()

    def get_complete(self, code, cursor_pos, timeout=None):
        """Generate complete request."""
        msg_id = self.client.complete(code, cursor_pos)
        self.shell_msg_queues_lock.acquire()
        try:
            queue = self.shell_msg_queues[msg_id]
        finally:
            self.shell_msg_queues_lock.release()

        try:
            recv_msg = queue.get(timeout=timeout)
            recv_content = recv_msg['content']
            self._logger.info(recv_content)
            if '_jupyter_types_experimental' in recv_content.get('metadata', {}):
                # If the reply has typing metadata, use it.
                # This metadata for typing is obviously experimental
                # and not documented yet.
                return [
                    (match['text'] + '\t' + match['type'], match['text'])
                    for match
                    in recv_content['metadata']['_jupyter_types_experimental']
                ]
            else:
                # Just say the completion is came from this plugin, otherwise.
                return [
                    (match + '\tHermes', match)
                    for match
                    in recv_content['matches']
                ]
        except Empty:
            self._logger.info("Completion timeout.")
        except Exception as ex:
            self._logger.exception(ex)
        finally:
            self.shell_msg_queues_lock.acquire()
            try:
                self.shell_msg_queues.pop(msg_id, None)
            finally:
                self.shell_msg_queues_lock.release()

        return []

    def get_inspection(self, code, cursor_pos, detail_level=0, timeout=None):
        """Get object inspection by sending a `inspect_request` message to kernel."""
        msg_id = self.client.inspect(code, cursor_pos, detail_level)
        self.shell_msg_queues_lock.acquire()
        try:
            queue = self.shell_msg_queues[msg_id]
        finally:
            self.shell_msg_queues_lock.release()

        try:
            recv_msg = queue.get(timeout=timeout)
            self._handle_inspect_reply(recv_msg['content']['data'])
        except Empty:
            self._logger.info("Object inspection timeout.")

        finally:
            self.shell_msg_queues_lock.acquire()
            try:
                self.shell_msg_queues.pop(msg_id, None)
            finally:
                self.shell_msg_queues_lock.release()
