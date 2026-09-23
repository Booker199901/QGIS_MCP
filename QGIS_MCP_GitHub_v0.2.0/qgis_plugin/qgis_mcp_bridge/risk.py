"""以保守規則判斷 Processing 或檔案輸出是否必須確認。"""

from pathlib import Path

KNOWN_PROCESSING_PROVIDERS = {
    "native",
    "qgis",
    "gdal",
    "grass",
    "grass7",
    "saga",
    "sagang",
}

DANGEROUS_ALGORITHM_WORDS = {
    "delete",
    "drop",
    "truncate",
    "update",
    "inplace",
    "renamefield",
    "refactorfields",
    "setstyle",
}


def path_requires_overwrite_confirmation(path_value):
    """只有真實、已存在的檔案輸出才要求覆寫確認。"""
    if not isinstance(path_value, str):
        return False
    normalized = path_value.strip()
    if not normalized or normalized.upper() in {"TEMPORARY_OUTPUT", "TEMPORARY", "MEMORY:"}:
        return False
    return Path(normalized).expanduser().exists()


def processing_requires_confirmation(algorithm_id, parameters, destination_names):
    """對未知 provider、疑似原地演算法、既有輸出或輸入輸出同一路徑採保守確認。"""
    provider_id = algorithm_id.split(":", 1)[0].lower() if ":" in algorithm_id else ""
    normalized_id = algorithm_id.lower()
    if provider_id not in KNOWN_PROCESSING_PROVIDERS:
        return True, "unknown_provider"
    if any(word in normalized_id for word in DANGEROUS_ALGORITHM_WORDS):
        return True, "potential_in_place_algorithm"

    input_paths = set()
    for name, value in parameters.items():
        if name not in destination_names and isinstance(value, str) and value.strip():
            input_paths.add(str(Path(value).expanduser()).lower())
    for destination_name in destination_names:
        output_value = parameters.get(destination_name)
        if path_requires_overwrite_confirmation(output_value):
            return True, "output_exists"
        if isinstance(output_value, str) and output_value.strip():
            normalized_output = str(Path(output_value).expanduser()).lower()
            if normalized_output in input_paths:
                return True, "input_output_same_path"
    return False, "new_output"
