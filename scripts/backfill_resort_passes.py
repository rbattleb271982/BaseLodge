#!/usr/bin/env python3
"""
scripts/backfill_resort_passes.py

Populates the resort_pass mapping table from existing Resort.pass_brands_json data.

Run once after the migration is applied:
    python scripts/backfill_resort_passes.py

Design:
- Skips resorts already present in resort_pass (idempotent).
- Skips resorts with no pass data or only ['None'].
- Marks the first pass in the list as is_primary=True; additional passes
  as is_primary=False (multi-pass resorts like Park City: Epic + Ikon).
- Reports a summary on completion.

Safety: Does NOT touch Resort.pass_brands_json or any legacy columns.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Resort, ResortPass


VALID_PASS_NAMES = set(ResortPass.VALID_PASS_NAMES)

# Normalize legacy/variant spellings stored in pass_brands_json to canonical form.
PASS_NAME_NORMALIZER = {
    'MountainCollective': 'Mountain Collective',
    'Mountain_Collective': 'Mountain Collective',
    'mountain collective': 'Mountain Collective',
    'epic': 'Epic',
    'ikon': 'Ikon',
    'indy': 'Indy',
    'other': 'Other',
}


def normalize_pass_name(name):
    """Normalize a pass name string to canonical form."""
    if not name:
        return name
    return PASS_NAME_NORMALIZER.get(name, name)


def backfill():
    with app.app_context():
        # Track already-mapped (resort_id, pass_name) pairs for idempotent operation.
        # Works at the individual row level so partially-mapped resorts still get
        # any missing passes added.
        already_mapped_pairs = set(
            (row.resort_id, row.pass_name)
            for row in ResortPass.query.with_entities(ResortPass.resort_id, ResortPass.pass_name).all()
        )

        all_resorts = Resort.query.all()

        inserted = 0
        skipped_no_data = 0
        skipped_already_mapped = 0
        skipped_invalid = 0

        for resort in all_resorts:
            brands = resort.get_pass_brands_list()

            # Filter: remove 'None', blank, and invalid values
            brands = [b for b in brands if b and b != 'None']

            if not brands:
                skipped_no_data += 1
                continue

            for i, brand in enumerate(brands):
                brand = normalize_pass_name(brand)
                if brand not in VALID_PASS_NAMES:
                    print(f"  ⚠  Resort {resort.id} ({resort.name}): unrecognised pass '{brand}' — skipping")
                    skipped_invalid += 1
                    continue
                if (resort.id, brand) in already_mapped_pairs:
                    skipped_already_mapped += 1
                    continue
                rp = ResortPass(
                    resort_id=resort.id,
                    pass_name=brand,
                    is_primary=(i == 0),
                )
                db.session.add(rp)
                inserted += 1

        db.session.commit()

        total = len(all_resorts)
        print("\n" + "=" * 60)
        print("Resort Pass Backfill — complete")
        print("=" * 60)
        print(f"  Total resorts inspected : {total}")
        print(f"  Rows inserted           : {inserted}")
        print(f"  Already mapped (skipped): {skipped_already_mapped}")
        print(f"  No pass data (skipped)  : {skipped_no_data}")
        print(f"  Invalid pass (skipped)  : {skipped_invalid}")
        print("=" * 60 + "\n")

        # Spot-check: show pass distribution
        from sqlalchemy import func
        dist = (
            db.session.query(ResortPass.pass_name, func.count(ResortPass.id))
            .group_by(ResortPass.pass_name)
            .order_by(func.count(ResortPass.id).desc())
            .all()
        )
        print("Pass distribution in resort_pass table:")
        for pass_name, count in dist:
            print(f"  {pass_name:<25} {count:>4} resort(s)")
        print()


if __name__ == '__main__':
    backfill()
