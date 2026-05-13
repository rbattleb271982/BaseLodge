from sqlalchemy import func


def get_ambiguous_resort_names(db_session, Resort) -> frozenset:
    """
    Single GROUP BY query — returns a frozenset of resort names that appear
    more than once in the resort table.  Called once at app startup and cached
    as a module-level frozenset; O(1) membership checks everywhere else.
    """
    rows = (
        db_session.query(Resort.name)
        .group_by(Resort.name)
        .having(func.count(Resort.id) > 1)
        .all()
    )
    return frozenset(r.name for r in rows)


def resort_display_name(resort, ambiguous_names: frozenset) -> str:
    """
    Returns a disambiguated display name when needed.

    Qualifier logic:
      - US / CA  → state_code  (2-letter: "WA", "ON")
      - all other countries → country_code  ("FR", "AT", "SE")
      - no qualifier available → plain name (no suffix)

    Canonical DB name, slug, and URL are never modified.
    """
    if not resort:
        return ""
    name = resort.name or ""
    if not name or name not in ambiguous_names:
        return name

    cc = (
        getattr(resort, "country_code", None)
        or getattr(resort, "country", None)
        or ""
    ).upper()

    if cc in ("US", "CA"):
        qualifier = (
            getattr(resort, "state_code", None)
            or getattr(resort, "state", None)
            or ""
        ).strip()
    else:
        qualifier = cc

    return f"{name} ({qualifier})" if qualifier else name
