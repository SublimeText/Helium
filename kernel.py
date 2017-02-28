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
from websocket import create_connection
from uuid import uuid4
from datetime import datetime

import sublime

JUPYTER_PROTOCOL_VERSION = '5.0'

MSG_TYPE_EXECUTE_REQUEST = 'execute_request'
MSG_TYPE_EXECUTE_RESULT = 'execute_result'
MSG_TYPE_EXECUTE_REPLY = 'execute_reply'
MSG_TYPE_COMPLETE_REQUEST = 'complete_request'
MSG_TYPE_COMPLETE_REPLY = 'complete_reply'


def extract_content(messages, msg_type):
    """Extract content from messages received from a kernel."""
    return [
        message['content']
        for message
        in messages
        if message['header']['msg_type'] == msg_type]


def extract_data(result):
    """Extract plain text data."""
    try:
        return result['data']
    except KeyError:
        return ""


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
        max_shown_input_length=(
            sublime
            .load_settings("Hermes.sublime-settings")
            .get("max_shown_input_length"))
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
        self._run_commands = {
            "text/plain": self._output_to_view
        }
        self._max_shown_input_length = max_shown_input_length

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

    def _communicate(self, message):
        """Send `message` to the kernel and return `reply` for it."""
        sock = create_connection(self._ws_url)
        sock.send(json.dumps(message).encode())
        replies = []
        while True:
            reply = json.loads(sock.recv())
            replies.append(reply)
            if reply["msg_type"].endswith("_reply"):
                break
        return replies

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
        sublime.active_window().focus_view(view)
        view.set_scratch(True)  # avoids prompting to save
        view.settings().set("word_wrap", "false")

    def _output_to_view(self, code: str, result: str) -> None:
        self.activate_view()
        view = self.get_view()
        view.set_read_only(False)
        if len(code) > self._max_shown_input_length:
            # Truncate if input if too long.
            # Truncation of the output should be each kernel's deal.
            code = code[:self._max_shown_input_length] + "..."
        for line in ["Input:", code, "Output:", result, "---", "\n"]:
            view.run_command(
                'append',
                {'characters': line + "\n"})
        view.set_read_only(True)

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
            content = extract_content(
                reply,
                MSG_TYPE_EXECUTE_RESULT)
            if len(content) == 0:
                return
            result, = content
            data = extract_data(result)
            for mime_type in data:
                if mime_type in self._run_commands:
                    self._run_commands[mime_type](
                        code,
                        data[mime_type])

        header = self._gen_header(MSG_TYPE_EXECUTE_REQUEST)
        content = dict(
            code=code,
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
        self._async_communicate(message, callback)

    def get_complete(self, code, cursor_pos):
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
        reply = self._communicate(message)
        content, = extract_content(reply, MSG_TYPE_COMPLETE_REPLY)
        return content["matches"]
