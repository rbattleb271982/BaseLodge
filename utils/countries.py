COUNTRIES = {
  "AR": "Argentina",
  "AU": "Australia",
  "BG": "Bulgaria",
  "CA": "Canada",
  "CL": "Chile",
  "CZ": "Czech Republic",
  "DE": "Germany",
  "ES": "Spain",
  "FR": "France",
  "GL": "Greenland",
  "IS": "Iceland",
  "IT": "Italy",
  "JP": "Japan",
  "NZ": "New Zealand",
  "NO": "Norway",
  "PL": "Poland",
  "RO": "Romania",
  "SI": "Slovenia",
  "SK": "Slovakia",
  "SE": "Sweden",
  "CH": "Switzerland",
  "TR": "Turkey",
  "US": "United States",
  "XK": "Kosovo"
}


def is_valid_country_code(code):
    """Returns True if code is a valid 2-letter ISO code in COUNTRIES."""
    if not isinstance(code, str) or len(code) != 2:
        return False
    return code.upper() in COUNTRIES


def country_name_from_code(code):
    """Returns full country name from COUNTRIES if valid, else None."""
    if not isinstance(code, str) or len(code) != 2:
        return None
    return COUNTRIES.get(code.upper())


def country_code_from_name(name):
    """Reverse-map full country name to ISO-2 code. Returns None if not found or ambiguous."""
    if not isinstance(name, str):
        return None
    
    # Normalize: strip, casefold, collapse multiple spaces
    normalized = ' '.join(name.strip().split()).casefold()
    
    if not normalized:
        return None
    
    # Build reverse lookup
    matches = []
    for code, country_name in COUNTRIES.items():
        if country_name.casefold() == normalized:
            matches.append(code)
    
    # Return None if no match or ambiguous (multiple matches)
    if len(matches) == 1:
        return matches[0]
    return None
