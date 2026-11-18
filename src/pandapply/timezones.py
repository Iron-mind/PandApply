"""Human-friendly timezone input normalized to a portable IANA identifier."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalize_timezone(value: str) -> str:
    value = value.strip()
    if value.upper() in ("UTC", "GMT", "Z"):
        return "UTC"
    offset = re.fullmatch(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::00)?", value, re.IGNORECASE)
    if offset:
        sign, hours = offset.group(1), int(offset.group(2))
        if hours == 0:
            return "UTC"
        # IANA's Etc/GMT names use POSIX's reversed sign convention.
        value = f"Etc/GMT{'+' if sign == '-' else '-'}{hours}"
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Zona horaria no reconocida. Usa una ciudad como America/Bogota o un desfase "
                         "como UTC-5. Para desfases con minutos, usa una ciudad como Asia/Kolkata.") from exc
    return value
