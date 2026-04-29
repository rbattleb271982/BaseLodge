"""
Centralized pass normalization and display helpers for BaseLodge.

Canonical stored values (snake_case):
    no_pass, no_pass_yet, epic, ikon, mountain_collective,
    powder_alliance, ski_california, indy, freedom, other

All inbound values are normalized via normalize_pass().
All outbound display uses display_pass_label() or format_passes_for_display().
"""

PASS_NORM_MAP = {
    "no pass":              "no_pass",
    "no_pass":              "no_pass",
    "i don't have a pass":  "no_pass",
    "none":                 "no_pass",
    "both":                 "no_pass",
    "not sure":             "no_pass_yet",
    "not sure yet":         "no_pass_yet",
    "no pass yet":          "no_pass_yet",
    "no_pass_yet":          "no_pass_yet",
    "epic":                 "epic",
    "epic local":           "epic",
    "epic pass":            "epic",
    "epic 4-day":           "epic",
    "ikon":                 "ikon",
    "ikon base":            "ikon",
    "ikon plus":            "ikon",
    "ikon session":         "ikon",
    "ikon pass":            "ikon",
    "freedom":              "freedom",
    "freedom pass":         "freedom",
    "indy":                 "indy",
    "indy pass":            "indy",
    "mountain collective":  "mountain_collective",
    "mountaincollective":   "mountain_collective",
    "mountain_collective":  "mountain_collective",
    "powder alliance":      "powder_alliance",
    "powderalliance":       "powder_alliance",
    "powder_alliance":      "powder_alliance",
    "ski california":       "ski_california",
    "skicalifornia":        "ski_california",
    "ski_california":       "ski_california",
    "other":                "other",
}

PASS_DISPLAY_MAP = {
    "no_pass":              "No pass",
    "no_pass_yet":          "No pass yet",
    "epic":                 "Epic",
    "ikon":                 "Ikon",
    "freedom":              "Freedom",
    "indy":                 "Indy",
    "mountain_collective":  "Mountain Collective",
    "powder_alliance":      "Powder Alliance",
    "ski_california":       "Ski California",
    "other":                "Other",
}

_NON_REAL_PASSES = frozenset({"no_pass", "no_pass_yet", "other", None, ""})


def normalize_pass(raw):
    """
    Normalize a single raw pass string to its canonical snake_case value.
    Returns None for empty/null input.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return PASS_NORM_MAP.get(key, key.replace(" ", "_"))


def display_pass_label(normalized):
    """
    Convert a normalized snake_case pass value to a human-readable display label.
    Returns '' for empty/None.
    """
    if not normalized:
        return ""
    return PASS_DISPLAY_MAP.get(normalized.strip().lower(), normalized)


def normalize_passes_string(pass_type_str):
    """
    Normalize a comma-separated pass_type string to canonical snake_case values.

    Multi-pass rules:
    - Real passes take priority over no_pass/no_pass_yet.
    - no_pass and no_pass_yet cannot coexist; no_pass_yet wins.
    - 'other' is dropped when combined with real passes.
    Returns '' for empty input.
    """
    if not pass_type_str:
        return ""
    parts = []
    for p in str(pass_type_str).split(","):
        n = normalize_pass(p.strip())
        if n:
            parts.append(n)

    real_passes = [p for p in parts if p not in _NON_REAL_PASSES]
    no_pass_parts = [p for p in parts if p in ("no_pass", "no_pass_yet")]

    if real_passes:
        return ",".join(real_passes)
    if no_pass_parts:
        return no_pass_parts[-1]
    return ""


def format_passes_for_display(pass_type_str):
    """
    Format a pass_type string for user-facing display.
    Normalizes values and maps to labels, including no_pass/no_pass_yet.
    Returns '' for empty/null.

    Examples:
        'epic'               -> 'Epic'
        'epic,ikon'          -> 'Epic · Ikon'
        'no_pass_yet'        -> 'No pass yet'
        'Not Sure'           -> 'No pass yet'   (legacy normalization)
        'MountainCollective' -> 'Mountain Collective'
    """
    if not pass_type_str:
        return ""
    labels = []
    for p in str(pass_type_str).split(","):
        norm = normalize_pass(p.strip())
        if norm:
            label = display_pass_label(norm)
            if label:
                labels.append(label)
    return " · ".join(labels)


def is_real_pass(pass_value):
    """Return True if the value represents a genuine ski pass (not no_pass/no_pass_yet/other)."""
    norm = normalize_pass(pass_value or "")
    return norm is not None and norm not in _NON_REAL_PASSES


def passes_match(pass_a, pass_b):
    """
    Return True if two pass_type strings share at least one real ski pass.
    Returns False if either side is empty, no_pass, no_pass_yet, or other.
    """
    if not pass_a or not pass_b:
        return False
    parts_a = {normalize_pass(p) for p in str(pass_a).split(",") if p.strip()}
    parts_b = {normalize_pass(p) for p in str(pass_b).split(",") if p.strip()}
    real_a = parts_a - _NON_REAL_PASSES - {None}
    real_b = parts_b - _NON_REAL_PASSES - {None}
    return bool(real_a & real_b)
