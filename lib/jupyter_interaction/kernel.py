"""Definition of Kernel class.

Kernel class provides interaction with Jupyter kernels.

by NEGORO Tetsuya, 2017
This code is under GPL2 License.
All rights are reserved.
"""

from threading import Thread
from queue import Queue
from urllib.parse import quote
import requests
import json
from websocket import create_connection
from uuid import uuid4
from datetime import datetime


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


def extract_data_if_text(execute_result_content):
    """Extract plain text data."""
    try:
        return execute_result_content['data']['text/plain']
    except KeyError:
        return ""


class Kernel(object):
    """Interact with a Jupyter kernel."""

    class AsyncCommunicator(Thread):
        """Communicator that runs  asynchroniously."""

        def __init__(self, kernel):
            """Initialize AsyncCommunicator class."""
            super(Kernel.AsyncCommunicator, self).__init__()
            self._kernel = kernel
            self.message_queue = Queue()

        def run(self):
            """Main routine."""
            while True:
                message, callback = self.message_queue.get()
                reply = self._kernel._communicate(message)
                callback(reply)

    def __init__(
        self,
        lang,
        kernel_id,
        manager
    ):
        """Initialize Kernel class.

        paramters
        ---------
        kernel_id str: kernel ID
        manager parent kernel manager
        """
        self._lang = lang
        self._kernel_id = kernel_id
        self.manager = manager
        self._ws_url = '{base_ws_url}/api/kernels/{kernel_id}/channels'.format(
            base_ws_url=manager.base_ws_url,
            kernel_id=quote(kernel_id))
        self._communicator = Kernel.AsyncCommunicator(self)
        self._communicator.start()

    @property
    def lang(self):
        """Language of kernel."""
        return self._lang

    @property
    def kernel_id(self):
        """ID of kernel."""
        return self._kernel_id

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
        self._communicator.message_queue.put((message, callback))

    def _gen_header(self, msg_type):
        return dict(
            version=JUPYTER_PROTOCOL_VERSION,
            kernel_id=self.kernel_id,
            msg_id=uuid4().hex,
            datetime=datetime.now().isoformat(),
            msg_type=msg_type
        )

    def run_code(self, code):
        """Run code with Jupyter kernel."""
        def callback(reply):
            result, = extract_content(
                reply,
                MSG_TYPE_EXECUTE_RESULT)
            data = extract_data_if_text(result)
            self._show_result(data)

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


class KernelManager(object):
    """Manage Jupyter kernels."""

    def __init__(
        self,
        base_url,
        base_ws_url=None,
    ):
        """Initialize a kernel manager.

        TODO: Deal with authentication.
        """
        if base_ws_url is None:
            _, _, url_body = base_url.partition("://")
            base_ws_url = "ws://" + url_body
        self._base_url = base_url
        self._base_ws_url = base_ws_url

    @property
    def base_url(self):
        """Base url of the jupyter process."""
        return self._base_url

    @property
    def base_ws_url(self):
        """Base WebSocket URL of the jupyter process."""
        return self._base_ws_url

    def get_jupyter_kernel_list(self):
        """Get the list of kernels."""
        url = '{}/api/kernels'.format(self.base_url)
        response = requests.get(url)
        return response.json()

    def start_kernel(self, lang):
        """Start kernel and return a `Kernel` instance."""
        url = '{}/api/kernels'.format(self.base_url)
        data = dict(name=lang)
        response = requests.post(
            url,
            data=json.dumps(data)).json()
        return Kernel(
            lang=response["name"],
            kernel_id=response["id"],
            manager=self)
