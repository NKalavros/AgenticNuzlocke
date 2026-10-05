"""Gen 1 major status: sleep counters are a condition, not a new plan each turn."""


def decode_status(value: int) -> str:
    if value & 7:
        return "SLP"
    for bit, name in ((8, "PSN"), (16, "BRN"), (32, "FRZ"), (64, "PAR")):
        if value & bit:
            return name
    return "OK" if value == 0 else "UNKNOWN"


def normalize_status(value: object) -> str:
    text = str(value or "UNKNOWN").upper()
    if text.startswith("SLP") or text in {"SLEEP", "ASLEEP"}:
        return "SLP"
    return text if text in {"OK", "PSN", "BRN", "FRZ", "PAR"} else "UNKNOWN"
