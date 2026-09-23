"""QGIS 外掛載入入口。"""


def classFactory(iface):  # noqa: N802,N803 - QGIS 外掛介面要求固定命名。
    """由 QGIS Plugin Manager 建立 Bridge 外掛實例。"""
    from .plugin import QgisMcpBridgePlugin

    return QgisMcpBridgePlugin(iface)
