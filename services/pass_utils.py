"""
Centralized pass normalization and display helpers for BaseLodge.

Canonical pass categories (stored snake_case):
    epic, ikon                                  — national passes (combinable, count toward 3-pass cap)
    indy, mountain_collective                   — regional passes, fully supported with resort coverage
    powder_alliance, freedom, ski_california    — regional passes, selectable (no resort matching yet)
    other                                       — catch-all real pass (combinable, counts toward cap)
    no_pass, no_pass_yet                        — exclusive, non-combinable

All inbound values are normalized via normalize_pass().
All outbound display uses display_pass_label() or format_passes_for_display().
"""

# Previously collapsed legacy passes — retained for reference only.
# No stored user records carry these raw slugs; all normalize to canonical values on read.
LEGACY_TO_MVP = {}

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
    "indy":                 "indy",
    "indy pass":            "indy",
    "indy_pass":            "indy",
    "mountain collective":  "mountain_collective",
    "mountaincollective":   "mountain_collective",
    "mountain_collective":  "mountain_collective",
    "powder alliance":      "powder_alliance",
    "powderalliance":       "powder_alliance",
    "powder_alliance":      "powder_alliance",
    "freedom":              "freedom",
    "freedom pass":         "freedom",
    "freedom_pass":         "freedom",
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
    "indy":                 "Indy",
    "mountain_collective":  "Mountain Collective",
    "powder_alliance":      "Powder Alliance",
    "freedom":              "Freedom Pass",
    "ski_california":       "Ski California",
    "other":                "Other pass",
}

# no_pass / no_pass_yet are the only exclusive non-real passes.
# All other slugs (epic, ikon, indy, mountain_collective, powder_alliance,
# freedom, ski_california, other) are real passes: combinable, count toward cap.
_NON_REAL_PASSES = frozenset({"no_pass", "no_pass_yet", None, ""})

# Canonical display order — matches select_pass pill order.
CANONICAL_PASS_ORDER = [
    "epic",
    "ikon",
    "indy",
    "mountain_collective",
    "powder_alliance",
    "freedom",
    "ski_california",
    "other",
    "no_pass",
    "no_pass_yet",
]
_VALID_PASS_SLUGS = frozenset(CANONICAL_PASS_ORDER)


def normalize_pass(raw):
    """
    Normalize a single raw pass string to its canonical snake_case value.
    Returns None for empty/null input.
    Unknown raw values are passed through as snake_case (spaces → underscores).
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
    - Real passes (epic, ikon, indy, mountain_collective, etc.) take priority over no_pass/no_pass_yet.
    - no_pass and no_pass_yet cannot coexist; last one wins.
    Returns '' for empty input.
    """
    if not pass_type_str:
        return ""
    parts = []
    for p in str(pass_type_str).split(","):
        n = normalize_pass(p.strip())
        if n:
            parts.append(n)

    real_passes   = [p for p in parts if p not in _NON_REAL_PASSES]
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
        'epic'                    -> 'Epic'
        'epic,ikon'               -> 'Epic · Ikon'
        'indy,ikon'               -> 'Ikon · Indy'
        'mountain_collective'     -> 'Mountain Collective'
        'no_pass_yet'             -> 'No pass yet'
        'Not Sure'                -> 'No pass yet'   (legacy normalization)
        'other'                   -> 'Other pass'
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


def normalize_pass_selection(pass_input):
    """
    Normalize, dedupe, validate, and sort pass values into canonical display order.

    Accepts a comma-separated string OR an iterable of raw/normalized pass values.
    Returns a comma-separated snake_case string ready to save to user.pass_type.

    Rules:
    - Each value is run through normalize_pass(); unknown slugs are dropped.
    - Duplicates are removed (first occurrence wins before ordering).
    - Real passes (epic, ikon, indy, etc.) take priority: if any real pass is present,
      exclusive pills (no_pass / no_pass_yet) are discarded.
    - If only exclusive values are present the last one is kept.
    - Real passes are sorted by CANONICAL_PASS_ORDER regardless of click order.
    - Does NOT enforce the 3-pass cap — callers must validate count separately.
    - Returns "" for empty/null input.

    Examples:
        "indy,epic,ikon"                -> "epic,ikon,indy"
        "ikon,epic"                     -> "epic,ikon"
        "no_pass,epic"                  -> "epic"             (real pass wins)
        "no_pass_yet,no_pass"           -> "no_pass"          (last exclusive wins)
        "epic,epic,ikon"                -> "epic,ikon"        (deduped)
        "mountain_collective"           -> "mountain_collective"
        ""                              -> ""
    """
    if not pass_input:
        return ""
    if isinstance(pass_input, str):
        raw_parts = [p.strip() for p in pass_input.split(",") if p.strip()]
    else:
        raw_parts = [str(p).strip() for p in pass_input if str(p).strip()]

    seen = set()
    normalized = []
    for p in raw_parts:
        n = normalize_pass(p)
        if n and n in _VALID_PASS_SLUGS and n not in seen:
            seen.add(n)
            normalized.append(n)

    real      = [p for p in normalized if p not in _NON_REAL_PASSES]
    exclusive = [p for p in normalized if p in _NON_REAL_PASSES]

    if real:
        ordered = [p for p in CANONICAL_PASS_ORDER if p in set(real)]
        return ",".join(ordered)
    if exclusive:
        return exclusive[-1]
    return ""


def count_real_passes(normalized_str):
    """
    Count real ski passes in a normalized comma-separated pass_type string.
    Excludes no_pass / no_pass_yet / empty.
    """
    if not normalized_str:
        return 0
    return sum(
        1 for p in normalized_str.split(",")
        if p.strip() and p.strip() not in _NON_REAL_PASSES
    )


def is_real_pass(pass_value):
    """Return True if the value represents a genuine ski pass (not no_pass/no_pass_yet)."""
    norm = normalize_pass(pass_value or "")
    return norm is not None and norm not in _NON_REAL_PASSES


def passes_match(pass_a, pass_b):
    """
    Return True if two pass_type strings share at least one real ski pass.
    Returns False if either side is empty, no_pass, or no_pass_yet.
    """
    if not pass_a or not pass_b:
        return False
    parts_a = {normalize_pass(p) for p in str(pass_a).split(",") if p.strip()}
    parts_b = {normalize_pass(p) for p in str(pass_b).split(",") if p.strip()}
    real_a  = parts_a - _NON_REAL_PASSES - {None}
    real_b  = parts_b - _NON_REAL_PASSES - {None}
    return bool(real_a & real_b)
