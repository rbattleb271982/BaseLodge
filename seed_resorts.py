"""
Seed script to populate the Resort table with all major resorts.
Run with: python seed_resorts.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Resort

STATE_FULL_NAMES = {
    "AK": "Alaska",
    "CA": "California",
    "CO": "Colorado",
    "ID": "Idaho",
    "ME": "Maine",
    "MI": "Michigan",
    "MT": "Montana",
    "NH": "New Hampshire",
    "NM": "New Mexico",
    "NY": "New York",
    "OR": "Oregon",
    "UT": "Utah",
    "VT": "Vermont",
    "WA": "Washington",
    "WY": "Wyoming",
}

RESORTS = [
    # Colorado
    {"name": "Aspen Snowmass", "state": "CO", "brand": "Ikon"},
    {"name": "Aspen Highlands", "state": "CO", "brand": "Ikon"},
    {"name": "Buttermilk", "state": "CO", "brand": "Ikon"},
    {"name": "Snowmass", "state": "CO", "brand": "Ikon"},
    {"name": "Beaver Creek", "state": "CO", "brand": "Epic"},
    {"name": "Breckenridge", "state": "CO", "brand": "Epic"},
    {"name": "Keystone", "state": "CO", "brand": "Epic"},
    {"name": "Vail", "state": "CO", "brand": "Epic"},
    {"name": "Copper Mountain", "state": "CO", "brand": "Ikon"},
    {"name": "Winter Park", "state": "CO", "brand": "Ikon"},
    {"name": "Eldora", "state": "CO", "brand": "Ikon"},
    {"name": "Telluride", "state": "CO", "brand": "Ikon"},
    {"name": "Monarch", "state": "CO", "brand": "Other"},
    {"name": "Sunlight", "state": "CO", "brand": "Other"},
    {"name": "Arapahoe Basin", "state": "CO", "brand": "Ikon"},
    {"name": "Loveland", "state": "CO", "brand": "Other"},
    {"name": "Steamboat", "state": "CO", "brand": "Ikon"},
    {"name": "Crested Butte", "state": "CO", "brand": "Epic"},
    
    # Utah
    {"name": "Alta", "state": "UT", "brand": "Ikon"},
    {"name": "Snowbird", "state": "UT", "brand": "Ikon"},
    {"name": "Solitude", "state": "UT", "brand": "Ikon"},
    {"name": "Brighton", "state": "UT", "brand": "Ikon"},
    {"name": "Park City", "state": "UT", "brand": "Epic"},
    {"name": "Deer Valley", "state": "UT", "brand": "Ikon"},
    {"name": "Snowbasin", "state": "UT", "brand": "Other"},
    {"name": "Powder Mountain", "state": "UT", "brand": "Other"},
    
    # California
    {"name": "Palisades Tahoe", "state": "CA", "brand": "Ikon"},
    {"name": "Northstar", "state": "CA", "brand": "Epic"},
    {"name": "Heavenly", "state": "CA", "brand": "Epic"},
    {"name": "Kirkwood", "state": "CA", "brand": "Epic"},
    {"name": "Mammoth Mountain", "state": "CA", "brand": "Ikon"},
    {"name": "June Mountain", "state": "CA", "brand": "Ikon"},
    {"name": "Big Bear", "state": "CA", "brand": "Other"},
    
    # Wyoming
    {"name": "Jackson Hole", "state": "WY", "brand": "Ikon"},
    {"name": "Grand Targhee", "state": "WY", "brand": "Ikon"},
    {"name": "Snow King", "state": "WY", "brand": "Other"},
    
    # Montana
    {"name": "Big Sky", "state": "MT", "brand": "Ikon"},
    {"name": "Whitefish Mountain", "state": "MT", "brand": "Other"},
    {"name": "Bridger Bowl", "state": "MT", "brand": "Other"},
    {"name": "Red Lodge Mountain", "state": "MT", "brand": "Other"},
    
    # Washington
    {"name": "Crystal Mountain", "state": "WA", "brand": "Ikon"},
    {"name": "Snoqualmie", "state": "WA", "brand": "Other"},
    {"name": "Mission Ridge", "state": "WA", "brand": "Other"},
    {"name": "Stevens Pass", "state": "WA", "brand": "Epic"},
    {"name": "Mt. Baker", "state": "WA", "brand": "Other"},
    
    # Oregon
    {"name": "Mt. Hood Meadows", "state": "OR", "brand": "Other"},
    {"name": "Timberline", "state": "OR", "brand": "Other"},
    {"name": "Mt. Bachelor", "state": "OR", "brand": "Ikon"},
    {"name": "Anthony Lakes", "state": "OR", "brand": "Other"},
    
    # Vermont
    {"name": "Killington", "state": "VT", "brand": "Ikon"},
    {"name": "Sugarbush", "state": "VT", "brand": "Ikon"},
    {"name": "Stowe", "state": "VT", "brand": "Epic"},
    {"name": "Stratton", "state": "VT", "brand": "Ikon"},
    {"name": "Jay Peak", "state": "VT", "brand": "Other"},
    {"name": "Smugglers Notch", "state": "VT", "brand": "Other"},
    {"name": "Mount Snow", "state": "VT", "brand": "Epic"},
    {"name": "Okemo", "state": "VT", "brand": "Epic"},
    
    # New Hampshire
    {"name": "Loon Mountain", "state": "NH", "brand": "Ikon"},
    {"name": "Cannon Mountain", "state": "NH", "brand": "Other"},
    {"name": "Waterville Valley", "state": "NH", "brand": "Other"},
    {"name": "Bretton Woods", "state": "NH", "brand": "Ikon"},
    {"name": "Wildcat Mountain", "state": "NH", "brand": "Other"},
    
    # Maine
    {"name": "Sunday River", "state": "ME", "brand": "Ikon"},
    {"name": "Sugarloaf", "state": "ME", "brand": "Ikon"},
    {"name": "Saddleback", "state": "ME", "brand": "Other"},
    
    # New York
    {"name": "Whiteface", "state": "NY", "brand": "Ikon"},
    {"name": "Gore Mountain", "state": "NY", "brand": "Other"},
    {"name": "Belleayre", "state": "NY", "brand": "Other"},
    {"name": "Hunter Mountain", "state": "NY", "brand": "Epic"},
    {"name": "Windham Mountain", "state": "NY", "brand": "Epic"},
    
    # New Mexico
    {"name": "Taos Ski Valley", "state": "NM", "brand": "Ikon"},
    {"name": "Ski Santa Fe", "state": "NM", "brand": "Other"},
    {"name": "Angel Fire", "state": "NM", "brand": "Other"},
    
    # Idaho
    {"name": "Sun Valley", "state": "ID", "brand": "Epic"},
    {"name": "Schweitzer", "state": "ID", "brand": "Other"},
    {"name": "Bogus Basin", "state": "ID", "brand": "Other"},
    {"name": "Brundage Mountain", "state": "ID", "brand": "Other"},
    
    # Michigan
    {"name": "Boyne Mountain", "state": "MI", "brand": "Other"},
    {"name": "Crystal Mountain MI", "state": "MI", "brand": "Other"},
    {"name": "Nubs Nob", "state": "MI", "brand": "Other"},
    
    # Alaska
    {"name": "Alyeska Resort", "state": "AK", "brand": "Ikon"},
]


def seed_resorts():
    with app.app_context():
        print("Updating resorts with state_full names...")
        
        for r in RESORTS:
            slug = r["name"].lower().replace(" ", "-").replace(".", "")
            state_full = STATE_FULL_NAMES.get(r["state"], r["state"])
            
            existing = Resort.query.filter_by(slug=slug).first()
            if existing:
                existing.state_full = state_full
            else:
                resort = Resort(
                    name=r["name"],
                    state=r["state"],
                    state_full=state_full,
                    brand=r["brand"],
                    slug=slug,
                    is_active=True
                )
                db.session.add(resort)
        
        db.session.commit()
        
        total = Resort.query.count()
        epic_count = Resort.query.filter_by(brand="Epic").count()
        ikon_count = Resort.query.filter_by(brand="Ikon").count()
        other_count = Resort.query.filter_by(brand="Other").count()
        
        print(f"Total resorts: {total}")
        print(f"  Epic: {epic_count}")
        print(f"  Ikon: {ikon_count}")
        print(f"  Other: {other_count}")


if __name__ == "__main__":
    seed_resorts()
