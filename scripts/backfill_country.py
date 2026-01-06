#!/usr/bin/env python3
"""
SECTION 2 — PROD BACKFILL + REVIEW REPORT

Backfills country_code and country_name for Resort records using existing legacy country values.
Uses utils/countries.py as the single source of truth.

Rules:
- Infer only when confident
- Leave NULL when uncertain
- Produce a review report for unresolved cases
"""

import os
import sys
import csv
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Resort
from utils.countries import COUNTRIES, is_valid_country_code, country_code_from_name, country_name_from_code


def run_backfill():
    """Run the country backfill on PROD database."""
    
    # Counters
    total_processed = 0
    successfully_backfilled = 0
    flagged_for_review = 0
    
    # Review report entries
    review_entries = []
    
    with app.app_context():
        resorts = Resort.query.all()
        total_processed = len(resorts)
        
        print(f"\n{'='*60}")
        print("COUNTRY BACKFILL - PROD DATABASE")
        print(f"{'='*60}")
        print(f"Total resorts to process: {total_processed}")
        print(f"COUNTRIES mapping has {len(COUNTRIES)} entries")
        print(f"{'='*60}\n")
        
        for resort in resorts:
            # Get legacy country value
            legacy_value = resort.country
            current_code = resort.country_code
            current_name = resort.country_name
            
            new_code = current_code
            new_name = current_name
            issue_reason = None
            needs_update = False
            
            # STEP A: Determine country_code if not already set
            if not current_code:
                if not legacy_value:
                    # No legacy value to work with
                    issue_reason = "missing"
                elif isinstance(legacy_value, str) and len(legacy_value.strip()) == 2:
                    # Check if it's a valid 2-letter code
                    candidate = legacy_value.strip().upper()
                    if is_valid_country_code(candidate):
                        new_code = candidate
                        needs_update = True
                    else:
                        issue_reason = "unrecognized"
                elif isinstance(legacy_value, str):
                    # Try to resolve as full country name
                    resolved = country_code_from_name(legacy_value)
                    if resolved:
                        new_code = resolved
                        needs_update = True
                    else:
                        # Check if ambiguous or just not found
                        normalized = ' '.join(legacy_value.strip().split()).casefold()
                        matches = [c for c, n in COUNTRIES.items() if n.casefold() == normalized]
                        if len(matches) > 1:
                            issue_reason = "ambiguous"
                        else:
                            issue_reason = "unrecognized"
                else:
                    issue_reason = "invalid_format"
            
            # STEP B: Set country_name if country_code exists but name doesn't
            if new_code and not current_name:
                resolved_name = country_name_from_code(new_code)
                if resolved_name:
                    new_name = resolved_name
                    needs_update = True
                elif not issue_reason:
                    # Code exists but not in our COUNTRIES mapping
                    issue_reason = "unrecognized"
            
            # Apply updates if needed
            if needs_update:
                if new_code and new_code != current_code:
                    resort.country_code = new_code
                if new_name and new_name != current_name:
                    resort.country_name = new_name
                successfully_backfilled += 1
            
            # Flag for review if there's an issue
            if issue_reason:
                flagged_for_review += 1
                review_entries.append({
                    'resort_id': resort.id,
                    'resort_name': resort.name,
                    'legacy_country_value': legacy_value or '',
                    'issue_reason': issue_reason
                })
        
        # Commit all changes
        db.session.commit()
        
        # Generate CSV report
        report_path = 'country_backfill_review.csv'
        if review_entries:
            with open(report_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['resort_id', 'resort_name', 'legacy_country_value', 'issue_reason'])
                writer.writeheader()
                writer.writerows(review_entries)
            print(f"Review report written to: {report_path}")
        else:
            print("No review entries - all resorts resolved successfully!")
        
        # Log summary
        print(f"\n{'='*60}")
        print("BACKFILL COMPLETE")
        print(f"{'='*60}")
        print(f"Total resorts processed: {total_processed}")
        print(f"Successfully backfilled: {successfully_backfilled}")
        print(f"Flagged for review: {flagged_for_review}")
        print(f"{'='*60}\n")
        
        return {
            'total': total_processed,
            'backfilled': successfully_backfilled,
            'flagged': flagged_for_review,
            'report_path': report_path if review_entries else None
        }


if __name__ == '__main__':
    run_backfill()
