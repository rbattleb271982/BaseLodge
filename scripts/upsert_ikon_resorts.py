"""
Safely upsert all Ikon Pass resorts into the resort table.
Idempotent: safe to run multiple times.
Run with: python scripts/upsert_ikon_resorts.py
"""

import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Resort

IKON_RESORTS = [
    # Alaska
    ("Alyeska Resort", "AK"),

    # California
    ("Palisades Tahoe", "CA"),
    ("Sierra-at-Tahoe", "CA"),
    ("Mammoth Mountain", "CA"),
    ("June Mountain", "CA"),
    ("Big Bear Mountain Resort", "CA"),
    ("Snow Valley", "CA"),

    # Colorado
    ("Aspen Snowmass", "CO"),
    ("Winter Park Resort", "CO"),
    ("Copper Mountain Resort", "CO"),
    ("Arapahoe Basin Ski Area", "CO"),
    ("Eldora Mountain Resort", "CO"),

    # Idaho
    ("Sun Valley", "ID"),
    ("Schweitzer", "ID"),

    # Maine
    ("Sugarloaf", "ME"),
    ("Sunday River", "ME"),

    # Michigan
    ("Boyne Mountain", "MI"),
    ("The Highlands", "MI"),

    # Montana
    ("Big Sky Resort", "MT"),

    # New Hampshire
    ("Loon Mountain", "NH"),

    # New Mexico
    ("Taos Ski Valley", "NM"),

    # Oregon
    ("Mt. Bachelor", "OR"),

    # Pennsylvania
    ("Camelback Resort", "PA"),
    ("Blue Mountain Resort", "PA"),

    # Utah
    ("Deer Valley Resort", "UT"),
    ("Solitude Mountain Resort", "UT"),
    ("Alta Ski Area", "UT"),
    ("Snowbird", "UT"),
    ("Brighton Resort", "UT"),
    ("Snowbasin Resort", "UT"),

    # Vermont
    ("Stratton Resort", "VT"),
    ("Sugarbush Resort", "VT"),
    ("Killington-Pico", "VT"),

    # Washington
    ("Crystal Mountain", "WA"),
    ("The Summit at Snoqualmie", "WA"),

    # West Virginia
    ("Snowshoe Mountain", "WV"),

    # Wyoming
    ("Jackson Hole Mountain Resort", "WY"),
]


def generate_slug(name, state):
    """Generate slug from resort name and state."""
    # Remove parentheses
    cleaned = re.sub(r'[()]', '', name)
    # Lowercase and replace spaces with hyphens
    slug = cleaned.lower().replace(" ", "-")
    # Remove any other special characters except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Remove consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Add state
    slug = f"{slug}-{state.lower()}"
    return slug


def upsert_ikon_resorts():
    """Upsert all Ikon resorts."""
    created = 0
    updated = 0
    skipped = 0
    
    with app.app_context():
        for name, state in IKON_RESORTS:
            slug = generate_slug(name, state)
            
            existing = Resort.query.filter_by(slug=slug).first()
            
            if existing:
                # Resort exists, check if update needed
                needs_update = False
                
                if existing.brand != "Ikon":
                    existing.brand = "Ikon"
                    needs_update = True
                
                if not existing.is_active:
                    existing.is_active = True
                    needs_update = True
                
                if needs_update:
                    db.session.commit()
                    updated += 1
                    print(f"  ✏️  UPDATED: {name} ({state}) - slug: {slug}")
                else:
                    skipped += 1
                    print(f"  ✓ SKIPPED: {name} ({state}) - already correct")
            else:
                # Create new resort
                resort = Resort(
                    name=name,
                    state=state,
                    state_full=None,
                    brand="Ikon",
                    slug=slug,
                    is_active=True
                )
                db.session.add(resort)
                db.session.commit()
                created += 1
                print(f"  ✨ CREATED: {name} ({state}) - slug: {slug}")
        
        # Print summary
        print("\n" + "=" * 70)
        print("UPSERT SUMMARY")
        print("=" * 70)
        print(f"Total processed: {len(IKON_RESORTS)}")
        print(f"Resorts created: {created}")
        print(f"Resorts updated: {updated}")
        print(f"Resorts skipped: {skipped}")
        print(f"\n✅ Upsert complete (idempotent - safe to re-run)")
        print("=" * 70)


if __name__ == "__main__":
    upsert_ikon_resorts()
