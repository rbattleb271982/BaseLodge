"""Search normalization utilities for BaseLodge name search.

normalize_for_search() is the single source of truth for how names are
stored in User.search_first_name / User.search_last_name and how query
strings are prepared before matching. Both storage and query MUST use
the identical function so prefix comparisons remain consistent.
"""

import re
import unicodedata

# Characters that do not decompose cleanly under Unicode NFD and need an
# explicit replacement before NFD is applied. Only lowercase variants are
# needed here because we lowercase before transliteration.
_TRANSLITERATION_MAP = str.maketrans({
    'ø': 'o',   # Søren → soren
    'ł': 'l',   # Łukasz → lukasz
    'đ': 'd',   # Đorđe → dorde
    'ð': 'd',   # Ðagur → dagur
    'þ': 'th',  # Þór → thor
    'æ': 'ae',  # Ærø → aeroe
    'œ': 'oe',  # Œuvre → oeuvre
    'ß': 'ss',  # Straße → strasse
})


def normalize_for_search(s: str) -> str:
    """Return a normalized, lowercase, Latin-only, space-separated version of s.

    Used both when storing search_first_name / search_last_name at write time
    and when normalizing query strings at search time.  Original first_name /
    last_name display values are NEVER modified.

    Normalization order:
    1. Lowercase (so the transliteration map only needs lowercase entries).
    2. Explicit transliteration for characters that do not decompose via NFD
       (ø → o, ß → ss, æ → ae, œ → oe, þ → th, ł → l, đ/ð → d).
    3. Unicode NFD decomposition — decomposes accented characters into base +
       combining mark (é → e + combining acute, ñ → n + combining tilde, etc.).
    4. Strip Unicode combining characters (category Mn) — removes the diacritics
       left after NFD (é → e, ñ → n, ü → u, ã → a, ç → c, François → francois).
    5. Apostrophes and hyphens → space (O'Connor → o connor,
       Battle-Baxter → battle baxter, Anne-Marie → anne marie).
    6. Collapse whitespace.

    Examples:
        José García    → jose garcia
        Søren          → soren
        François       → francois
        Müller         → muller
        Straße         → strasse
        O'Connor       → o connor
        Battle-Baxter  → battle baxter
        Łukasz Wójcik  → lukasz wojcik
    """
    if not s:
        return ''
    # 1. Lowercase
    s = s.lower()
    # 2. Explicit transliteration (before NFD so composed forms are caught)
    s = s.translate(_TRANSLITERATION_MAP)
    # 3. NFD decomposition
    s = unicodedata.normalize('NFD', s)
    # 4. Strip combining characters (diacritics)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # 5. Apostrophes and hyphens → space
    s = re.sub(r"['\u2018\u2019\u0060`]", ' ', s)   # ' ' ` variants
    s = re.sub(r'[-\u2013\u2014]', ' ', s)            # - – — variants
    # 6. Collapse whitespace
    s = ' '.join(s.split())
    return s


_LIKE_ESCAPE_CHAR = '\\'

def _escape_like(token: str) -> str:
    """Escape LIKE metacharacters in *token* using backslash as the escape char.

    Escaping order matters: backslash must be escaped first so we don't
    double-escape the escape chars we insert for % and _.
    """
    token = token.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
    token = token.replace('%', _LIKE_ESCAPE_CHAR + '%')
    token = token.replace('_', _LIKE_ESCAPE_CHAR + '_')
    return token


def build_name_search_clauses(normalized_q: str, first_col, last_col):
    """Build SQLAlchemy OR-able filter clauses for a multi-token name search.

    For an N-token normalized query, generates N-1 AND clauses (one per
    consecutive token-partition point) suitable for combining with OR in the
    caller's WHERE clause.

    LIKE metacharacters (%, _, \\) in any token are escaped with backslash
    before appending the prefix wildcard, preventing user input from matching
    unintended rows.

    For example, normalized_q = "jo sm" (2 tokens) produces:
        first_col LIKE 'jo%' ESCAPE '\\' AND last_col LIKE 'sm%' ESCAPE '\\'

    "mary ann sm" (3 tokens) produces:
        (first_col LIKE 'mary%' ESCAPE '\\' AND last_col LIKE 'ann sm%' ESCAPE '\\')
        OR
        (first_col LIKE 'mary ann%' ESCAPE '\\' AND last_col LIKE 'sm%' ESCAPE '\\')

    This handles multi-word first/last names without assuming first token =
    first name.

    Returns None if normalized_q has fewer than 2 tokens (insufficient query).
    """
    from sqlalchemy import and_
    tokens = normalized_q.split()
    if len(tokens) < 2:
        return None
    clauses = []
    for i in range(1, len(tokens)):
        first_part = _escape_like(' '.join(tokens[:i]))
        last_part  = _escape_like(' '.join(tokens[i:]))
        clauses.append(and_(
            first_col.like(first_part + '%', escape=_LIKE_ESCAPE_CHAR),
            last_col.like(last_part  + '%', escape=_LIKE_ESCAPE_CHAR),
        ))
    return clauses
