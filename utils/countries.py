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
  "XK": "Kosovo",
  "FI": "Finland",
  "KR": "South Korea",
  "CN": "China"
}


STATE_ABBR_MAP = {
    # United States — all 50 states
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    # Canadian provinces and territories
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
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
