"""組合所有 V1 QGIS 操作群組。"""

from .base import BaseOperations
from .canvas_geometry import CanvasGeometryOperations
from .features import FeatureOperations
from .formats import FormatOperations
from .processing import ProcessingOperations
from .project_layers import ProjectLayerOperations
from .raster import RasterOperations
from .styles import StyleOperations


class OperationHandler(
    ProjectLayerOperations,
    FeatureOperations,
    ProcessingOperations,
    StyleOperations,
    FormatOperations,
    RasterOperations,
    CanvasGeometryOperations,
    BaseOperations,
):
    """以 mixin 組合 V1 actions，同時維持單一共用 context。"""

    pass


__all__ = ["OperationHandler"]
