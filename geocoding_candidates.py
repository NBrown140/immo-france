from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import pandas as pd


STREET_TYPE_MAP = {
    "AV": "Avenue",
    "AVEN": "Avenue",
    "BD": "Boulevard",
    "BLD": "Boulevard",
    "RTE": "Route",
    "RT": "Route",
    "R": "Rue",
    "CHE": "Chemin",
    "CHEM": "Chemin",
    "ALL": "Allee",
    "PL": "Place",
    "SQ": "Square",
    "IMP": "Impasse",
    "RES": "Residence",
}

SUFFIX_MAP = {
    "B": "Bis",
    "T": "Ter",
    "Q": "Quater",
}

NORMALIZED_STREET_TYPES = set(STREET_TYPE_MAP.values())
SUFFIX_TOKENS = {value.upper() for value in SUFFIX_MAP.values()} | {key.upper() for key in SUFFIX_MAP}
STREET_ABBREVIATION_REPLACEMENTS = {
    "GAL": "General",
    "GEN": "General",
    "CDT": "Commandant",
    "CMDT": "Commandant",
    "CMT": "Commandant",
    "DOC": "Docteur",
    "DR": "Docteur",
    "MAL": "Marechal",
    "MAR": "Marechal",
    "ST": "Saint",
    "STE": "Sainte",
    "STE.": "Sainte",
    "N-D": "Notre-Dame",
    "ND": "Notre-Dame",
    "FBG": "Faubourg",
    "FG": "Faubourg",
    "TRA": "Traverse",
    "CR": "Cours",
}

PLACE_PREFIX_TOKENS = {
    "LOT",
    "LOTISSEMENT",
    "RES",
    "RESIDENCE",
    "RESID.",
    "CITE",
    "CIT",
    "IMM",
    "IMMEUBLE",
    "PARC",
    "RES.",
    "HAM",
    "HAMEAU",
    "VILLAGE",
    "CAMPAGNE",
    "ENSEMBLE",
}

ARRONDISSEMENT_LIMITS = {
    "Paris": (1, 20),
    "Lyon": (1, 9),
    "Marseille": (1, 16),
}

ARRONDISSEMENT_PATTERN = re.compile(
    r"^(?P<city>Paris|Lyon|Marseille)[\s-]+0?(?P<number>\d{1,2})(?:\s*(?:er|eme|e))?(?:\s+Arrondissement)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QCandidate:
    label: str
    street: str | None
    city: str | None


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_street_type(value: str) -> str:
    if not value:
        return ""
    key = value.upper().replace(".", "")
    return STREET_TYPE_MAP.get(key, value.title())


def _normalize_suffix(value: str) -> str:
    if not value:
        return ""
    key = value.upper().replace(".", "")
    return SUFFIX_MAP.get(key, value.upper())


def _normalize_street_name(value: str) -> str:
    if not value:
        return ""
    return _normalize_whitespace(value.title())


def _parse_arrondissement(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None
    match = ARRONDISSEMENT_PATTERN.match(value.strip())
    if not match:
        return None
    city = match.group("city").title()
    number = int(match.group("number"))
    min_number, max_number = ARRONDISSEMENT_LIMITS[city]
    if not (min_number <= number <= max_number):
        return None
    return city, number


def _format_arrondissement_name(city: str, number: int) -> str:
    ordinal = "1er" if number == 1 else f"{number}e"
    return f"{city} {ordinal} Arrondissement"


def _normalize_commune(value: str) -> str:
    if not value:
        return ""
    normalized = _normalize_whitespace(value.title())
    normalized = normalized.replace(" D'", " d'").replace("-D'", "-d'")
    arrondissement = _parse_arrondissement(normalized)
    if arrondissement:
        normalized = _format_arrondissement_name(*arrondissement)
    return normalized


def _replace_eme_suffix(value: str | None) -> str | None:
    if not value:
        return None
    replaced = re.sub(r"(\d+)\s*Eme\b", r"\1e", value, flags=re.IGNORECASE)
    replaced = re.sub(r"\s{2,}", " ", replaced).strip()
    if replaced == value.strip():
        return None
    return replaced


def _remove_city_eme_suffix(value: str | None) -> str | None:
    if not value:
        return None
    arrondissement = _parse_arrondissement(value)
    if arrondissement:
        city, _ = arrondissement
        return city
    replaced = re.sub(r"(\d+)\s*Eme\b", r"\1", value, flags=re.IGNORECASE)
    replaced = re.sub(r"\s{2,}", " ", replaced).strip()
    if replaced == value.strip():
        return None
    return replaced


def _expand_street_abbreviations(value: str | None) -> str | None:
    if not value:
        return None
    tokens = value.split()
    changed = False
    for idx, token in enumerate(tokens):
        normalized = token.upper().rstrip(".")
        replacement = STREET_ABBREVIATION_REPLACEMENTS.get(normalized)
        if not replacement and "-" in token:
            head, *tail = token.split("-")
            normalized_head = head.upper().rstrip(".")
            head_replacement = STREET_ABBREVIATION_REPLACEMENTS.get(normalized_head)
            if head_replacement:
                replacement = "-".join([head_replacement] + tail)
        if replacement:
            tokens[idx] = replacement
            changed = True
    if not changed:
        return None
    return " ".join(tokens)


def _strip_street_type(street: str | None) -> str | None:
    if not street:
        return None
    tokens = street.split()
    if not tokens:
        return None

    idx = 0
    saw_number = False
    while idx < len(tokens):
        token = tokens[idx]
        token_upper = token.upper().replace(".", "")
        if any(ch.isdigit() for ch in token):
            saw_number = True
            idx += 1
            continue
        if token_upper in SUFFIX_TOKENS:
            idx += 1
            continue
        if saw_number and token.isalpha() and len(token) <= 2:
            idx += 1
            continue
        break

    if idx >= len(tokens):
        return None

    type_candidate = tokens[idx].title()
    if type_candidate not in NORMALIZED_STREET_TYPES:
        return None

    stripped_tokens = tokens[:idx] + tokens[idx + 1 :]
    stripped = " ".join(stripped_tokens).strip()
    return stripped or None


def _strip_leading_number(street: str | None) -> str | None:
    if not street:
        return None
    tokens = street.split()
    idx = 0
    while idx < len(tokens) and any(char.isdigit() for char in tokens[idx]):
        idx += 1
    if idx == 0 or idx >= len(tokens):
        return None
    stripped = " ".join(tokens[idx:]).strip()
    return stripped or None


def _strip_place_prefix(street: str | None) -> str | None:
    if not street:
        return None
    tokens = street.split()
    changed = False
    while tokens:
        normalized = tokens[0].upper().rstrip(".")
        if normalized in PLACE_PREFIX_TOKENS:
            tokens.pop(0)
            changed = True
            continue
        break
    if not changed or not tokens:
        return None
    return " ".join(tokens)


def _remove_single_letter_tokens(street: str | None) -> str | None:
    if not street:
        return None
    tokens = street.split()
    filtered = [token for token in tokens if len(token.strip(" .'-")) > 1]
    if len(filtered) == len(tokens):
        return None
    stripped = " ".join(filtered).strip()
    return stripped or None


def construct_address(row: pd.Series) -> tuple[str | None, str | None, str | None]:
    number = _clean(row.get("No voie"))
    suffix = _clean(row.get("B/T/Q"))
    street_type = _clean(row.get("Type de voie"))
    street_name = _clean(row.get("Voie"))
    postal_code = _clean(row.get("Code postal"))
    commune = _clean(row.get("Commune"))

    suffix = _normalize_suffix(suffix)
    street_type = _normalize_street_type(street_type)
    street_name = _normalize_street_name(street_name)
    commune = _normalize_commune(commune)

    number_part = " ".join(part for part in [number, suffix] if part).strip()
    street_part = " ".join(part for part in [street_type, street_name] if part).strip()

    street = " ".join(part for part in [number_part, street_part] if part).strip()
    street = street or None

    postal_code = postal_code or None
    commune = commune or None
    return street, commune, postal_code


def _build_street_variants(street: str | None) -> OrderedDict[str, str | None]:
    variants: OrderedDict[str, str | None] = OrderedDict()

    def add(label: str, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if not normalized or label in variants:
            return
        variants[label] = normalized

    add("street_original", street)
    add("street_replace_eme", _replace_eme_suffix(street))

    stripped = _strip_street_type(street)
    add("street_strip_type", stripped)
    add("street_strip_type_replace_eme", _replace_eme_suffix(stripped) if stripped else None)

    expanded = _expand_street_abbreviations(street)
    add("street_expand_abbrev", expanded)
    add("street_expand_abbrev_replace_eme", _replace_eme_suffix(expanded) if expanded else None)

    stripped_expanded = _expand_street_abbreviations(stripped) if stripped else None
    add("street_strip_type_expand", stripped_expanded)
    add("street_strip_type_expand_replace_eme", _replace_eme_suffix(stripped_expanded) if stripped_expanded else None)

    numberless = _strip_leading_number(street)
    add("street_no_number", numberless)
    add("street_no_number_strip_type", _strip_street_type(numberless) if numberless else None)

    add("street_remove_place_prefix", _strip_place_prefix(street))
    add("street_remove_single_letters", _remove_single_letter_tokens(street))

    variants["street_none"] = None
    return variants


def build_city_variants(city: str | None) -> OrderedDict[str, str | None]:
    variants: OrderedDict[str, str | None] = OrderedDict()

    normalized = city.strip() if city else None
    arrondissement = _parse_arrondissement(normalized) if normalized else None

    if normalized and arrondissement:
        normalized = _format_arrondissement_name(*arrondissement)

    removed = _remove_city_eme_suffix(normalized)
    if removed:
        variants["city_remove_eme"] = removed

    if normalized:
        variants["city_original"] = normalized
    else:
        variants["city_missing"] = None

    if arrondissement:
        parent_city, _ = arrondissement
        variants["city_arrondissement_parent"] = parent_city

    if "city_original" not in variants:
        variants["city_original"] = normalized
    if "city_remove_eme" not in variants and normalized:
        variants["city_remove_eme"] = normalized
    if "city_missing" not in variants:
        variants["city_missing"] = None

    return variants



ORDERED_COMBINATIONS: list[tuple[str, str]] = [
    ("city_arrondissement_parent", "street_original"),
    ("city_arrondissement_parent", "street_strip_type"),
    ("city_arrondissement_parent", "street_expand_abbrev"),
    ("city_arrondissement_parent", "street_replace_eme"),
    ("city_remove_eme", "street_original"),
    ("city_remove_eme", "street_strip_type"),
    ("city_remove_eme", "street_expand_abbrev"),
    ("city_remove_eme", "street_replace_eme"),
    ("city_original", "street_original"),
    ("city_original", "street_strip_type"),
    ("city_original", "street_expand_abbrev"),
    ("city_original", "street_replace_eme"),
    ("city_arrondissement_parent", "street_strip_type_expand"),
    ("city_remove_eme", "street_strip_type_expand"),
    ("city_original", "street_strip_type_expand"),
    ("city_arrondissement_parent", "street_strip_type_replace_eme"),
    ("city_remove_eme", "street_strip_type_replace_eme"),
    ("city_original", "street_strip_type_replace_eme"),
    ("city_arrondissement_parent", "street_expand_abbrev_replace_eme"),
    ("city_remove_eme", "street_expand_abbrev_replace_eme"),
    ("city_original", "street_expand_abbrev_replace_eme"),
    ("city_arrondissement_parent", "street_strip_type_expand_replace_eme"),
    ("city_remove_eme", "street_strip_type_expand_replace_eme"),
    ("city_original", "street_strip_type_expand_replace_eme"),
    ("city_arrondissement_parent", "street_no_number"),
    ("city_remove_eme", "street_no_number"),
    ("city_original", "street_no_number"),
    ("city_arrondissement_parent", "street_no_number_strip_type"),
    ("city_remove_eme", "street_no_number_strip_type"),
    ("city_original", "street_no_number_strip_type"),
    ("city_arrondissement_parent", "street_remove_place_prefix"),
    ("city_remove_eme", "street_remove_place_prefix"),
    ("city_original", "street_remove_place_prefix"),
    ("city_arrondissement_parent", "street_remove_single_letters"),
    ("city_remove_eme", "street_remove_single_letters"),
    ("city_original", "street_remove_single_letters"),
    ("city_arrondissement_parent", "street_none"),
    ("city_remove_eme", "street_none"),
    ("city_original", "street_none"),
    ("city_missing", "street_none"),
]


def build_q_candidates(street: str | None, city: str | None) -> list[QCandidate]:
    street_variants = _build_street_variants(street)
    city_variants = build_city_variants(city)
    candidates: list[QCandidate] = []

    for city_key, street_key in ORDERED_COMBINATIONS:
        if city_key not in city_variants or street_key not in street_variants:
            continue
        city_value = city_variants[city_key]
        street_value = street_variants[street_key]
        label = f"{city_key}|{street_key}"
        if street_key == "street_none":
            candidates.append(QCandidate(label, None, city_value))
            continue
        if street_value is None:
            continue
        candidates.append(QCandidate(label, street_value, city_value))

    return candidates
