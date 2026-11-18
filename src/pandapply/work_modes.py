"""Shared work-mode input for setup, dashboard and matching."""

import re

ALIASES = {"remote": "remote", "remoto": "remote", "hybrid": "hybrid", "hibrido": "hybrid",
           "híbrido": "hybrid", "onsite": "onsite", "presencial": "onsite",
           "any": "any", "cualquiera": "any", "todas": "any"}


def parse_work_modes(value: str | list[str] | None) -> list[str]:
    if value is None or value == "" or value == []:
        return []
    parts = re.split(r"\s*(?:,|;|\by\b|\band\b)\s*", value.strip().casefold()) if isinstance(value, str) else value
    if not isinstance(parts, list) or not parts:
        raise ValueError("Elige remote, hybrid, onsite o varias separadas por comas; any acepta todas.")
    modes = []
    for part in parts:
        if not isinstance(part, str) or part.strip().casefold() not in ALIASES:
            raise ValueError("Elige remote, hybrid, onsite o varias separadas por comas; any acepta todas.")
        mode = ALIASES[part.strip().casefold()]
        if mode not in modes:
            modes.append(mode)
    if "any" in modes:
        if len(modes) != 1:
            raise ValueError("Usa any sola para aceptar todas las modalidades.")
        return []
    return modes


def work_mode_preference(value: str | list[str] | None) -> str | list[str] | None:
    modes = parse_work_modes(value)
    return modes[0] if len(modes) == 1 else modes or None


def work_mode_label(value: str | list[str] | None) -> str:
    return ", ".join(parse_work_modes(value)) or "any"
