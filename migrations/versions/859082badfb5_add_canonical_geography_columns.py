"""add_canonical_geography_columns

Revision ID: 859082badfb5
Revises: 32fe4ef07f7c
Create Date: 2025-12-25 04:12:09.316957

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '859082badfb5'
down_revision = '32fe4ef07f7c'
branch_labels = None
depends_on = None

# Country name mapping (ISO-2 code -> display name)
COUNTRY_NAMES = {
    "US": "United States",
    "CA": "Canada",
    "JP": "Japan",
    "FR": "France",
    "CH": "Switzerland",
    "AT": "Austria",
    "IT": "Italy",
}

# US State mapping (code -> name)
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming"
}

# Canada Province mapping (code -> name)
CA_PROVINCE_NAMES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "NS": "Nova Scotia",
    "NT": "Northwest Territories", "NU": "Nunavut", "ON": "Ontario",
    "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon"
}


def upgrade():
    # Step 1: Add new columns (nullable initially)
    op.add_column('resort', sa.Column('country_code', sa.String(10), nullable=True))
    op.add_column('resort', sa.Column('country_name', sa.String(100), nullable=True))
    op.add_column('resort', sa.Column('state_code', sa.String(50), nullable=True))
    op.add_column('resort', sa.Column('state_name', sa.String(100), nullable=True))
    
    # Step 2: Backfill data from existing columns
    conn = op.get_bind()
    
    # Get all resorts
    resorts = conn.execute(text("SELECT id, country, state, state_full FROM resort")).fetchall()
    
    print(f"\n=== GEOGRAPHY MIGRATION: Processing {len(resorts)} resorts ===\n")
    
    unmapped = []
    
    for resort in resorts:
        resort_id, country, state, state_full = resort
        
        # Map country_code (existing country is already ISO-2)
        country_code = country if country else "US"  # Default to US if null
        country_name = COUNTRY_NAMES.get(country_code, country_code)
        
        # Map state_code and state_name based on country
        if country_code == "US":
            # US uses 2-letter codes
            state_code = state
            state_name = state_full or US_STATE_NAMES.get(state, state)
        elif country_code == "CA":
            # Canada uses 2-letter codes
            state_code = state
            state_name = state_full or CA_PROVINCE_NAMES.get(state, state)
        else:
            # International: state is already full name, use as both code and name
            state_code = state
            state_name = state_full or state
        
        # Check for unmapped states
        if country_code == "US" and state not in US_STATE_NAMES:
            unmapped.append(f"US state not in mapping: {state}")
        elif country_code == "CA" and state not in CA_PROVINCE_NAMES:
            unmapped.append(f"CA province not in mapping: {state}")
        
        # Update the row
        conn.execute(text("""
            UPDATE resort 
            SET country_code = :country_code, 
                country_name = :country_name, 
                state_code = :state_code, 
                state_name = :state_name
            WHERE id = :id
        """), {
            "id": resort_id,
            "country_code": country_code,
            "country_name": country_name,
            "state_code": state_code,
            "state_name": state_name
        })
    
    if unmapped:
        print(f"WARNING: {len(unmapped)} unmapped entries:")
        for entry in unmapped[:10]:
            print(f"  - {entry}")
    
    # Step 3: Verify specific resorts
    print("\n=== VERIFICATION ===")
    
    # Check Colorado resorts
    co_resorts = conn.execute(text("""
        SELECT name, country_code, state_code, state_name 
        FROM resort 
        WHERE state_code = 'CO' AND country_code = 'US' 
        LIMIT 5
    """)).fetchall()
    print(f"Colorado resorts: {len(co_resorts)}")
    for r in co_resorts:
        print(f"  - {r[0]} ({r[1]}/{r[2]})")
    
    # Check BC resorts (Whistler)
    bc_resorts = conn.execute(text("""
        SELECT name, country_code, state_code, state_name 
        FROM resort 
        WHERE state_code = 'BC' AND country_code = 'CA' 
        LIMIT 5
    """)).fetchall()
    print(f"British Columbia resorts: {len(bc_resorts)}")
    for r in bc_resorts:
        print(f"  - {r[0]} ({r[1]}/{r[2]})")
    
    # Check for Whistler specifically
    whistler = conn.execute(text("""
        SELECT id, name, country_code, state_code, state_name 
        FROM resort 
        WHERE name LIKE '%Whistler%'
    """)).fetchall()
    print(f"Whistler Blackcomb found: {len(whistler) > 0}")
    if whistler:
        print(f"  - {whistler[0]}")
    
    print("\n=== MIGRATION COMPLETE ===\n")


def downgrade():
    # Remove the new columns
    op.drop_column('resort', 'state_name')
    op.drop_column('resort', 'state_code')
    op.drop_column('resort', 'country_name')
    op.drop_column('resort', 'country_code')
