"""
Display-only name formatting utilities.
Never modifies stored data — only used at render time.
"""


def format_name(name):
    """
    Return a display-ready title-cased version of a name string.
    Handles hyphenated names correctly.

    Examples:
        richard             → Richard
        RICHARD             → Richard
        rIcHaRd             → Richard
        richard battle-baxter → Richard Battle-Baxter
    """
    if not name:
        return ""

    def cap_part(part):
        return "-".join([p.capitalize() for p in part.split("-")])

    return " ".join([cap_part(p) for p in name.split()])
