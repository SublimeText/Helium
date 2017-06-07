"""Definition of KernelConnection class.

KernelConnection class provides interaction with Jupyter kernels.

by NEGORO Tetsuya, 2017
This code is under GPL2 License.
All rights are reserved.
"""

from threading import Thread
from queue import Queue
from urllib.parse import quote
import json
from uuid import uuid4
from datetime import datetime
import re

from websocket import create_connection
import sublime

from .utils import (
    show_password_input,
)


JUPYTER_PROTOCOL_VERSION = '5.0'

REPLY_STATUS_OK = "ok"
REPLY_STATUS_ERROR = "error"
REPLY_STATUS_ABORT = "abort"

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


class JupyterReply(object):
    """Parse replies from Jupyter."""

    def __init__(self, messages, message_type="execute", *, logger=None):
        """Parse message and initialize self."""
        self._display_data = []
        self._stream_stdout = []
        self._stream_stderr = []
        self._stream_other = []
        for message in messages:
            logger.info(message)
            content = message.get("content", dict())
            if "execution_count" in content:
                self._execution_count = content["execution_count"]
            msg_type = get_msg_type(message)
            # switch by msg_type.
            if msg_type.endswith("_reply"):
                self._status = content["status"]
            if msg_type == MSG_TYPE_COMPLETE_REPLY:
                self._matches = content["matches"]
            elif msg_type == MSG_TYPE_INSPECT_REPLY:
                found = content["found"]
                if found:
                    self._inspect_data = content["data"]
                else:
                    self._inspect_data = "No object inspection found."
            elif msg_type == MSG_TYPE_ERROR:
                self._ename = content["ename"]
                self._evalue = content["evalue"]
                self._traceback = content["traceback"]
            elif msg_type == MSG_TYPE_DISPLAY_DATA:
                self._display_data.append(content["data"])
            elif msg_type == MSG_TYPE_EXECUTE_RESULT:
                self._execute_result = content["data"]
            elif msg_type == MSG_TYPE_STREAM:
                if content["name"] == "stdout":
                    self._stream_stdout.append(content["text"])
                elif content["name"] == "stderr":
                    self._stream_stderr.append(content["text"])
                else:
                    self._stream_other.append(content["text"])
            elif msg_type == MSG_TYPE_STATUS:
                self._execution_state = content["execution_state"]

    @property
    def status(self):
        return self._status

    @property
    def ename(self):
        return self._ename

    @property
    def evalue(self):
        return self._evalue

    @property
    def traceback(self):
        return self._traceback

    @property
    def execution_count(self):
        return self._execution_count

    @property
    def display_data(self):
        try:
            return self._display_data
        except AttributeError:
            return [dict()]

    @property
    def execute_result(self):
        try:
            return self._execute_result
        except AttributeError:
            return dict()

    @property
    def stream_stdout(self):
        return self._stream_stdout

    @property
    def stream_stderr(self):
        return self._stream_stderr

    @property
    def stream_other(self):
        return self._stream_other

    @property
    def matches(self):
        return self._matches

    @property
    def inspect_data(self):
        return self._inspect_data


class KernelConnection(object):
    """Interact with a Jupyter kernel."""

    class AsyncCommunicator(Thread):
        """Communicator that runs  asynchroniously."""

        def __init__(self, kernel):
            """Initialize AsyncCommunicator class."""
            super(KernelConnection.AsyncCommunicator, self).__init__()
            self._kernel = kernel
            self.message_queue = Queue()

        def run(self):
            """Main routine."""
            # TODO: log
            while True:
                try:
                    message, callback = self.message_queue.get()
                    reply = self._kernel._communicate(message)
                    callback(reply)
                except Exception as err:
                    print(err)

    def __init__(
        self,
        lang,
        kernel_id,
        manager,
        auth_type=("no_auth", "password", "token")[0],
        *,
        auth_info=None,
        token=None,
        logger=None
    ):
        """Initialize KernelConnection class.

        paramters
        ---------
        kernel_id str: kernel ID
        manager parent kernel manager
        """
        self._lang = lang
        self._kernel_id = kernel_id
        self.manager = manager
        self._ws_url = '{base_ws_url}/api/kernels/{kernel_id}/channels'.format(
            base_ws_url=manager.base_ws_url(),
            kernel_id=quote(kernel_id))
        self._async_communicator = KernelConnection.AsyncCommunicator(self)
        self._async_communicator.start()
        self._logger = logger
        self._auth_type = auth_type
        self._auth_info = auth_info
        self._token = token

    @property
    def lang(self):
        """Language of kernel."""
        return self._lang

    @property
    def kernel_id(self):
        """ID of kernel."""
        return self._kernel_id

    @property
    def view_name(self):
        """The name of output view."""
        return "*Hermes Output* [{lang}] {kernel_id}".format(
            lang=self.lang,
            kernel_id=self.kernel_id)

    def _create_connection(self, connect_kwargs):
        if self._auth_type == "no_auth":
            sock = create_connection(
                self._ws_url,
                **connect_kwargs)
        elif self._auth_type == "password":
            sock = create_connection(
                self._ws_url,
                http_proxy_auth=self._auth_info,
                **connect_kwargs)
        elif self._auth_type == "token":
            header_auth_body = "token {token}".format(
                token=self._token)
            header = dict(Authorization=header_auth_body)
            sock = create_connection(
                self._ws_url,
                header=header)
        return sock

    def _communicate(self, message, timeout=None) -> JupyterReply:
        """Send `message` to the kernel and return `reply` for it."""
        # Use `create_connection`'s default value unless `timeout` is set.
        if timeout is not None:
            connect_kwargs = dict(timeout=timeout)
        else:
            connect_kwargs = dict()

        sock = self._create_connection(connect_kwargs)
        sock.send(json.dumps(message).encode())
        replies = []
        replied = False
        while True:
            # The code here requires refactoring.
            # The code to interpret reply messages is devided into here and `JupyterReply` class.
            # Maybe it's better choice to remove `JupyterReply` class and
            # let all message interpretation processed here.
            reply = json.loads(sock.recv())
            replies.append(reply)
            self._logger.info(reply)
            msg_type = get_msg_type(reply)
            if msg_type.endswith("_reply"):
                # Kernel sends status first, or XX_reply first?
                if self._execution_state == 'idle':
                    break
                replied = True
            if msg_type == MSG_TYPE_STATUS:
                self._execution_state = reply["content"]["execution_state"]
                if self._execution_state == 'idle' and replied:
                    break
            elif msg_type == MSG_TYPE_INPUT_REQUEST:
                content = reply["content"]

                def send_input(value):
                    input_reply = dict(
                        header=self._gen_header(MSG_TYPE_INPUT_REPLY),
                        parent_header=reply["header"],
                        content=dict(value=value),
                        channel='stdin',
                        metadata={},
                        buffers={})
                    sock.send(json.dumps(input_reply).encode())

                prompt = content["prompt"]

                def interrupt():
                    self.manager.interrupt_kernel(self.kernel_id)

                if content["password"]:
                    show_password_input(prompt, send_input, interrupt)

                else:
                    (
                        sublime
                        .active_window()
                        .show_input_panel(
                            prompt,
                            "",
                            send_input,
                            lambda x: None,
                            interrupt
                        )
                    )

        reply_obj = JupyterReply(replies, logger=self._logger)
        return reply_obj

    def _async_communicate(self, message, callback):
        self._async_communicator.message_queue.put((message, callback))

    def _gen_header(self, msg_type):
        return dict(
            version=JUPYTER_PROTOCOL_VERSION,
            kernel_id=self.kernel_id,
            msg_id=uuid4().hex,
            datetime=datetime.now().isoformat(),
            msg_type=msg_type
        )

    def activate_view(self):
        """Activate view to show the output of kernel."""
        view = self.get_view()
        current_view = sublime.active_window().active_view()
        sublime.active_window().focus_view(view)
        view.set_scratch(True)  # avoids prompting to save
        view.settings().set("word_wrap", "false")
        sublime.active_window().focus_view(current_view)

    def _handle_display_data(self, reply: JupyterReply) -> None:
        # import base64
        # import tempfile
        # decoded = base64.b64decode(data)
        # with tempfile.TemporaryFile(delete=False, suffix=".png") as out_file:
        #     out_file.write(decoded)
        #     view_output = "Saved the figure to '{out_file}'.\n".format(
        #         out_file=out_file.name)
        #     self._write_to_view(view_output)
        for mime_data in reply.display_data:
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
                file_size = self.get_view().size()
                region = sublime.Region(file_size, file_size)
                self.get_view().add_phantom(
                    HERMES_FIGURE_PHANTOMS,
                    region,
                    content,
                    sublime.LAYOUT_BLOCK)
                self._logger.info("Created phantom {}".format(content))
            if "text/markdown" in mime_data:
                # Some kernel (such as IRkernel) sends text in display_data.
                result = mime_data["text/markdown"]
                lines = "\n(display data): {result}".format(result=result)
                self._write_to_view(lines)

    def _output_input_code(self, code, execution_count):
        line = "In[{execution_count}]: {code}".format(
            execution_count=execution_count,
            code=code)
        self._write_to_view(line)

    def _handle_result_text(self, reply: JupyterReply) -> None:
        try:
            # lines = "\n\033[1;31mOut[{execution_count}]:\033[0m {result}".format(
            lines = "\nOut[{execution_count}]: {result}".format(
                execution_count=reply.execution_count,
                result=reply.execute_result["text/plain"])
            self._write_to_view(lines)
        except KeyError:
            pass

    def _handle_error(self, reply: JupyterReply) -> None:
        try:
            lines = "\nError[{execution_count}]: {ename}, {evalue}.\nTraceback:\n{traceback}".format(
                execution_count=reply.execution_count,
                ename=reply.ename,
                evalue=reply.evalue,
                traceback="\n".join(reply.traceback))
            self._write_to_view(remove_ansi_escape(lines))
        except AttributeError:
            # Just there is no error.
            pass

    def _handle_stream(self, reply: JupyterReply) -> None:
        # Currently don't consider real time catching of streams.
        try:
            lines = []
            if len(reply.stream_stdout) > 0:
                lines += ["\n(stdout):"] + reply.stream_stdout
            if len(reply.stream_stderr) > 0:
                lines += ["\n(stderr):"] + reply.stream_stderr
            if len(reply.stream_other) > 0:
                lines += ["\n(other stream):"] + reply.stream_other
            self._write_to_view("\n".join(lines))
        except AttributeError:
            # Just there is no error.
            pass

    def _handle_inspect_reply(self, reply: JupyterReply):
        window = sublime.active_window()
        if window.find_output_panel(HERMES_OBJECT_INSPECT_PANEL) is not None:
            window.destroy_output_panel(HERMES_OBJECT_INSPECT_PANEL)
        view = window.create_output_panel(HERMES_OBJECT_INSPECT_PANEL)
        try:
            text = remove_ansi_escape(reply.inspect_data["text/plain"])
            view.run_command(
                'append',
                {'characters': text})
            window.run_command(
                'show_panel',
                dict(panel="output." + HERMES_OBJECT_INSPECT_PANEL))
        except KeyError:
            pass

    def _write_to_view(self, text: str) -> None:
        self.activate_view()
        view = self.get_view()
        view.set_read_only(False)
        view.run_command(
            'append',
            {'characters': text})
        view.set_read_only(True)

    def update_status_bar(self):
        self._communicate()

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
        def callback(reply):
            try:
                self._output_input_code(code, reply.execution_count)
                self._handle_stream(reply)
                self._handle_display_data(reply)
                self._handle_error(reply)
                self._handle_result_text(reply)
            finally:
                # Separator should be written if an undealt error occur while handling reply.
                self._write_to_view("\n\n" + OUTPUT_VIEW_SEPARATOR + "\n\n")

        header = self._gen_header(MSG_TYPE_EXECUTE_REQUEST)
        content = dict(
            code=code,
            silent=False,
            store_history=True,
            user_expressions={},
            allow_stdin=True)
        message = dict(
            header=header,
            parent_header={},
            channel='shell',
            content=content,
            metadata={},
            buffers={})
        self._async_communicate(message, callback)
        info_message = "Kernel executed code ```{code}```.".format(code=code)
        self._logger.info(info_message)

    @property
    def execution_state(self):
        try:
            return self._execution_state
        except AttributeError:
            return "unknown"

    def get_complete(self, code, cursor_pos, timeout=None):
        """Generate complete request."""
        header = self._gen_header(MSG_TYPE_COMPLETE_REQUEST)
        content = dict(
            code=code,
            cursor_pos=cursor_pos,
            silent=False,
            store_history=True,
            user_expressions={},
            allow_stdin=False)
        message = dict(
            header=header,
            parent_header={},
            channel='shell',
            content=content,
            metadata={},
            buffers={})
        reply = self._communicate(message, timeout)
        return reply.matches

    def get_inspection(self, code, cursor_pos, detail_level=0, timeout=None):
        """Get object inspection by sending a `inspect_request` message to kernel."""
        header = self._gen_header(MSG_TYPE_INSPECT_REQUEST)
        content = dict(
            code=code,
            cursor_pos=cursor_pos,
            detail_level=detail_level,
            silent=False,
            store_history=False,
            user_expressions={},
            allow_stdin=False)
        message = dict(
            header=header,
            parent_header={},
            channel='shell',
            content=content,
            metadata={},
            buffers={})
        reply = self._communicate(message, timeout)
        self._handle_inspect_reply(reply)
