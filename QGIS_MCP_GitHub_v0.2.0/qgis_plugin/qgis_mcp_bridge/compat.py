"""集中隔離 QGIS 3.44/Qt5 與 QGIS 4.x/Qt6 的 API 差異。"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QMessageBox


def message_box_yes():
    """取得兩個 Qt 主版本都可使用的 Yes enum。"""
    standard = getattr(QMessageBox, "StandardButton", QMessageBox)
    return standard.Yes


def message_box_cancel():
    """取得兩個 Qt 主版本都可使用的 Cancel enum。"""
    standard = getattr(QMessageBox, "StandardButton", QMessageBox)
    return standard.Cancel


def checked_state():
    """取得 Qt5/Qt6 共通的 Checked enum。"""
    check_state = getattr(Qt, "CheckState", Qt)
    return check_state.Checked


def unchecked_state():
    """取得 Qt5/Qt6 共通的 Unchecked enum。"""
    check_state = getattr(Qt, "CheckState", Qt)
    return check_state.Unchecked


def user_role():
    """取得 Qt5/Qt6 共通的 UserRole enum。"""
    item_role = getattr(Qt, "ItemDataRole", Qt)
    return item_role.UserRole
