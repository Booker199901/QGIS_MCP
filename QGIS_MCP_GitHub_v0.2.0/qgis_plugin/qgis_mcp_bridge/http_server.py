"""使用 QtNetwork 在 QGIS 主執行緒提供最小化 loopback HTTP Bridge。"""

import hmac
import json

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtNetwork import QHostAddress, QTcpServer

from .constants import BRIDGE_API_VERSION, MAX_HEADER_BYTES, MAX_REQUEST_BYTES


class BridgeHttpServer(QObject):
    """只接受已認證 POST /v1/command 的本機 HTTP/1.1 Server。"""

    def __init__(self, router, token, parent=None):
        super().__init__(parent)
        self._router = router  # Router 只會在建立此外掛的 QGIS 主執行緒執行。
        self._expected_authorization = f"Bearer {token}".encode()
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept_connections)
        self._buffers = {}  # 每個 QTcpSocket 保留尚未完整接收的 bytes。
        self._dispatching = False  # modal 確認的巢狀 event loop 不得重入另一個命令。

    @property
    def port(self):
        """回傳系統分配的實際 loopback port。"""
        return int(self._server.serverPort())

    def start(self):
        """要求作業系統在 127.0.0.1 配置隨機可用 port。"""
        if not self._server.listen(QHostAddress("127.0.0.1"), 0):
            raise RuntimeError(self._server.errorString())

    def stop(self):
        """關閉所有已接受 socket 與監聽器，不碰其他程序連線。"""
        for socket in list(self._buffers):
            socket.abort()
            socket.deleteLater()
        self._buffers.clear()
        self._server.close()

    def _accept_connections(self):
        """接收所有等待中的 loopback 連線並掛上增量讀取事件。"""
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if not socket.peerAddress().isLoopback():
                socket.abort()
                socket.deleteLater()
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda active_socket=socket: self._read_socket(active_socket))
            socket.disconnected.connect(lambda active_socket=socket: self._cleanup_socket(active_socket))

    def _cleanup_socket(self, socket):
        """釋放單一已中斷連線的 buffer 與 Qt 物件。"""
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _read_socket(self, socket):
        """累積資料，直到收到完整 header 與 Content-Length body。"""
        if socket not in self._buffers:
            return
        buffer = self._buffers[socket]
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_HEADER_BYTES + MAX_REQUEST_BYTES:
            self._send_json(socket, 413, {"error": "request_too_large"})
            return
        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            if len(buffer) > MAX_HEADER_BYTES:
                self._send_json(socket, 431, {"error": "headers_too_large"})
            return
        try:
            request_line, headers = self._parse_headers(bytes(buffer[:header_end]))
            content_length = int(headers.get(b"content-length", b"0"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(socket, 400, {"error": "invalid_http_request"})
            return
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(socket, 413, {"error": "request_too_large"})
            return
        body_start = header_end + 4
        if len(buffer) - body_start < content_length:
            return
        body = bytes(buffer[body_start : body_start + content_length])
        self._handle_request(socket, request_line, headers, body)

    @staticmethod
    def _parse_headers(header_bytes):
        """解析最小必要 HTTP headers；重複欄位採最後一筆且不支援 chunked body。"""
        lines = header_bytes.split(b"\r\n")
        if not lines:
            raise ValueError("missing request line")
        request_line = lines[0].decode("ascii")
        headers = {}
        for line in lines[1:]:
            if b":" not in line:
                raise ValueError("invalid header")
            name, value = line.split(b":", 1)
            headers[name.strip().lower()] = value.strip()
        return request_line, headers

    def _handle_request(self, socket, request_line, headers, body):
        """完成認證、路由與 JSON 驗證後才執行 QGIS 操作。"""
        parts = request_line.split(" ")
        if len(parts) != 3 or parts[0] != "POST" or parts[1] != "/v1/command":
            self._send_json(socket, 404, {"error": "not_found"})
            return
        if headers.get(b"transfer-encoding", b"").lower() == b"chunked":
            self._send_json(socket, 400, {"error": "chunked_not_supported"})
            return
        if headers.get(b"content-type", b"").split(b";", 1)[0].lower() != b"application/json":
            self._send_json(socket, 415, {"error": "json_required"})
            return
        if not hmac.compare_digest(headers.get(b"authorization", b""), self._expected_authorization):
            self._send_json(socket, 401, {"error": "unauthorized"})
            return
        if headers.get(b"x-qgis-mcp-api-version", b"") != str(BRIDGE_API_VERSION).encode("ascii"):
            self._send_json(socket, 409, {"error": "api_version_mismatch"})
            return
        if self._dispatching:
            self._send_json(socket, 409, {"error": "bridge_busy"})
            return
        try:
            payload = json.loads(body.decode("utf-8"))
            self._dispatching = True
            try:
                response = self._router.dispatch(payload)
            finally:
                self._dispatching = False
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(socket, 400, {"error": "invalid_json"})
            return
        except Exception as error:  # 最後防線只記錄型別，不回傳 traceback 或敏感參數。
            QgsMessageLog.logMessage(
                f"Bridge HTTP dispatch failed: {type(error).__name__}",
                "QGIS MCP",
                Qgis.MessageLevel.Critical,
            )
            self._send_json(socket, 500, {"error": "internal_error"})
            return
        self._send_json(socket, 200, response)

    def _send_json(self, socket, status, payload):
        """送出固定 Connection: close 的 UTF-8 JSON 回應並清理 socket。"""
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            409: "Conflict",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            431: "Request Header Fields Too Large",
            500: "Internal Server Error",
        }.get(status, "Error")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        socket.write(header + body)
        socket.flush()
        socket.disconnectFromHost()
        self._buffers.pop(socket, None)
