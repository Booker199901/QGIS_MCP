"""Bridge 內部可預期錯誤，避免把 traceback 直接傳給 AI。"""


class BridgeError(Exception):
    """帶穩定錯誤碼與安全 details 的領域錯誤。"""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code  # 供 MCP Client 做穩定的錯誤分流。
        self.message = message  # 使用者可讀且不得包含 token 或密碼。
        self.details = details or {}  # 只加入有助修正的結構化內容。


class UserDeniedError(BridgeError):
    """使用者在 QGIS GUI 拒絕危險操作。"""

    def __init__(self):
        super().__init__("USER_DENIED", "使用者已在 QGIS 視窗拒絕此操作。")
