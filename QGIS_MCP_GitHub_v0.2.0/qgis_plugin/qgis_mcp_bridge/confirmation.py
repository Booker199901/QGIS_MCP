"""在 QGIS GUI 中執行不可由 MCP Client 代替的真人確認。"""

from qgis.PyQt.QtWidgets import QMessageBox

from .compat import message_box_cancel, message_box_yes
from .errors import UserDeniedError
from .settings import tr


class ConfirmationService:
    """顯示預設拒絕的危險操作確認視窗。"""

    def __init__(self, parent):
        self._parent = parent  # 將視窗綁定 QGIS 主視窗，避免出現在背景。

    def require(self, operation_name, summary, details):
        """等待使用者按下允許；取消、關閉或其他結果一律視為拒絕。"""
        dialog = QMessageBox(self._parent)
        dialog.setIcon(QMessageBox.Icon.Warning if hasattr(QMessageBox, "Icon") else QMessageBox.Warning)
        dialog.setWindowTitle(tr("QGIS MCP 危險操作確認", "QGIS MCP confirmation"))
        dialog.setText(operation_name)
        dialog.setInformativeText(summary)
        dialog.setDetailedText(details)
        yes_button = message_box_yes()
        cancel_button = message_box_cancel()
        dialog.setStandardButtons(yes_button | cancel_button)
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        result = dialog.exec()
        if result != int(yes_button):
            raise UserDeniedError()
