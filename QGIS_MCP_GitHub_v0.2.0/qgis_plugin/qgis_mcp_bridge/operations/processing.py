"""實作全部已註冊 QGIS Processing providers、演算法說明與背景執行。"""

from qgis.core import Qgis, QgsApplication, QgsProcessingContext

from ..errors import BridgeError
from ..risk import processing_requires_confirmation
from ..utils import json_safe, require_bool, require_int, require_string


class ProcessingOperations:
    """在開放全部 Processing 能力的同時保留驗證與安全確認。"""

    def op_list_processing_providers(self, _params):
        """列出目前實例 registry 內所有 Processing providers。"""
        providers = []
        for provider in QgsApplication.processingRegistry().providers():
            providers.append(
                {
                    "id": provider.id(),
                    "name": provider.name(),
                    "long_name": provider.longName(),
                    "version": provider.versionInfo(),
                    "is_active": provider.isActive(),
                    "algorithm_count": len(provider.algorithms()),
                }
            )
        return {"providers": sorted(providers, key=lambda item: item["id"]), "count": len(providers)}

    def op_search_processing_algorithms(self, params):
        """以 ID、名稱、顯示名稱或群組做不分大小寫搜尋。"""
        query = require_string(params, "query", allow_empty=True).casefold()
        provider_id = require_string(params, "provider_id", allow_empty=True).casefold()
        limit = require_int(params, "limit", 100, minimum=1, maximum=500)
        matches = []
        for algorithm in QgsApplication.processingRegistry().algorithms():
            algorithm_provider = algorithm.provider()
            current_provider_id = (
                algorithm_provider.id() if algorithm_provider else algorithm.id().split(":", 1)[0]
            )
            if provider_id and current_provider_id.casefold() != provider_id:
                continue
            searchable = " ".join(
                [
                    algorithm.id(),
                    algorithm.name(),
                    algorithm.displayName(),
                    algorithm.group(),
                    algorithm.groupId(),
                ]
            ).casefold()
            if query and query not in searchable:
                continue
            matches.append(self._algorithm_summary(algorithm))
        matches.sort(key=lambda item: item["algorithm_id"])
        truncated = len(matches) > limit
        return {
            "algorithms": matches[:limit],
            "returned_count": min(len(matches), limit),
            "total_matches": len(matches),
            "truncated": truncated,
        }

    def op_get_processing_algorithm_help(self, params):
        """以 JSON Schema 友善摘要呈現參數、destination 與輸出。"""
        algorithm_id = require_string(params, "algorithm_id")
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if algorithm is None:
            raise BridgeError("PROCESSING_ALGORITHM_NOT_FOUND", f"找不到演算法：{algorithm_id}")
        parameters = [self._parameter_summary(parameter) for parameter in algorithm.parameterDefinitions()]
        destinations = [parameter.name() for parameter in algorithm.destinationParameterDefinitions()]
        outputs = [
            {
                "name": output.name(),
                "description": output.description(),
                "type": output.type(),
                "definition": json_safe(output.toVariantMap()),
            }
            for output in algorithm.outputDefinitions()
        ]
        return {
            **self._algorithm_summary(algorithm),
            "short_help": algorithm.shortHelpString(),
            "help_url": algorithm.helpUrl(),
            "parameters": parameters,
            "destination_parameters": destinations,
            "outputs": outputs,
        }

    def op_run_processing_algorithm(self, params):
        """驗證參數、副作用與目的地後，非同步排入 QgsTaskManager。"""
        algorithm_id = require_string(params, "algorithm_id")
        algorithm_parameters = params.get("parameters")
        if not isinstance(algorithm_parameters, dict):
            raise BridgeError("INVALID_PARAMETERS", "parameters 必須是 JSON object。")
        add_outputs = require_bool(params, "add_outputs_to_project", True)
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if algorithm is None:
            raise BridgeError("PROCESSING_ALGORITHM_NOT_FOUND", f"找不到演算法：{algorithm_id}")

        context = QgsProcessingContext()
        context.setProject(self.project())
        valid, error_message = algorithm.checkParameterValues(algorithm_parameters, context)
        if not valid:
            raise BridgeError(
                "INVALID_PARAMETERS",
                "Processing 參數未通過演算法驗證。",
                {"algorithm_id": algorithm_id, "error": error_message},
            )
        destination_names = {parameter.name() for parameter in algorithm.destinationParameterDefinitions()}
        requires_confirmation, reason = processing_requires_confirmation(
            algorithm_id,
            algorithm_parameters,
            destination_names,
        )
        if requires_confirmation:
            destinations = {
                name: json_safe(algorithm_parameters.get(name)) for name in sorted(destination_names)
            }
            self.confirmation.require(
                "執行可能修改或覆寫資料的 Processing 演算法",
                f"即將執行「{algorithm.displayName()}」，安全判斷原因：{reason}。",
                "演算法 ID：{}\nProvider：{}\n輸出目的地：{}\n\n請確認輸入與輸出後再允許。".format(
                    algorithm_id,
                    algorithm.provider().id() if algorithm.provider() else "unknown",
                    json_safe(destinations),
                ),
            )
        job = self.jobs.start_processing(algorithm, algorithm_parameters, add_outputs)
        return {"status": "queued", "risk_reason": reason, **job}

    def op_get_job_status(self, params):
        """取得 JobManager 保存的有限公開狀態。"""
        return self.jobs.get_status(require_string(params, "job_id"))

    def op_get_job_result(self, params):
        """取得已完成或目前工作的結果與錯誤。"""
        return self.jobs.get_result(require_string(params, "job_id"))

    def op_cancel_job(self, params):
        """要求取消指定工作，不假裝底層已立即停止。"""
        return self.jobs.cancel(require_string(params, "job_id"))

    @staticmethod
    def _algorithm_summary(algorithm):
        """建立不含 QGIS QObject 的最小演算法摘要。"""
        provider = algorithm.provider()
        return {
            "algorithm_id": algorithm.id(),
            "name": algorithm.name(),
            "display_name": algorithm.displayName(),
            "group": algorithm.group(),
            "group_id": algorithm.groupId(),
            "provider_id": provider.id() if provider else algorithm.id().split(":", 1)[0],
            "flags": json_safe(algorithm.flags()),
        }

    @staticmethod
    def _parameter_summary(parameter):
        """標示必要性、預設值與 provider 自訂 metadata。"""
        optional_flag = Qgis.ProcessingParameterFlag.Optional
        is_optional = bool(parameter.flags() & optional_flag)
        return {
            "name": parameter.name(),
            "description": parameter.description(),
            "type": parameter.type(),
            "optional": is_optional,
            "default": json_safe(parameter.defaultValue()),
            "flags": json_safe(parameter.flags()),
            "metadata": json_safe(parameter.metadata()),
            "definition": json_safe(parameter.toVariantMap()),
        }
