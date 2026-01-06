#!/usr/bin/env python3
"""
========================================
DEV → PROD Resort Sync Script
========================================

PURPOSE:
  Safely synchronize resort data from DEV database to PROD database.

BEHAVIOR:
  - Matches resorts by ID ONLY
  - Updates existing PROD resorts with DEV data
  - Inserts new resorts that exist in DEV but not PROD
  - NEVER deletes any resort from PROD
  - NEVER changes or reassigns IDs
  - Idempotent: safe to run multiple times

REQUIREMENTS:
  - DEV_DATABASE_URL environment variable (source)
  - PROD_DATABASE_URL environment variable (target)
  - Must pass --confirm flag to execute changes

USAGE:
  # Dry run (shows what would change, no writes):
  python scripts/sync_resorts_to_prod.py

  # Execute sync:
  python scripts/sync_resorts_to_prod.py --confirm

WARNING:
  This script WRITES to the production database when --confirm is passed.
  Always run without --confirm first to review changes.

========================================
"""

import os
import sys
import argparse
from datetime import datetime

try:
    from sqlalchemy import create_engine, text
except ImportError:
    print("ERROR: sqlalchemy is required. Install with: pip install sqlalchemy")
    sys.exit(1)


def get_env_var(name):
    """Get required environment variable or exit."""
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: {name} environment variable is not set.")
        sys.exit(1)
    return value


def load_dev_resorts(dev_engine):
    """Load all resorts from DEV database."""
    query = text("""
        SELECT 
            id, name, slug,
            country_code, country_name, country_name_override,
            state_code, state_name, state, state_full,
            country,
            pass_brands, pass_brands_json, brand,
            is_active, is_region
        FROM resort
        ORDER BY id
    """)
    
    with dev_engine.connect() as conn:
        result = conn.execute(query)
        resorts = [dict(row._mapping) for row in result]
    
    return resorts


def get_prod_resort_ids(prod_engine):
    """Get all existing resort IDs from PROD database."""
    query = text("SELECT id FROM resort")
    
    with prod_engine.connect() as conn:
        result = conn.execute(query)
        return {row[0] for row in result}


def sync_resorts(dev_resorts, prod_engine, prod_ids, dry_run=True):
    """
    Sync resorts from DEV to PROD.
    
    Returns:
        dict with counts: updated, inserted, skipped, errors
    """
    stats = {
        'updated': 0,
        'inserted': 0,
        'skipped': 0,
        'errors': []
    }
    
    update_sql = text("""
        UPDATE resort SET
            name = :name,
            slug = :slug,
            country_code = :country_code,
            country_name = :country_name,
            country_name_override = :country_name_override,
            state_code = :state_code,
            state_name = :state_name,
            state = :state,
            state_full = :state_full,
            country = :country,
            pass_brands = :pass_brands,
            pass_brands_json = :pass_brands_json,
            brand = :brand,
            is_active = :is_active,
            is_region = :is_region
        WHERE id = :id
    """)
    
    insert_sql = text("""
        INSERT INTO resort (
            id, name, slug,
            country_code, country_name, country_name_override,
            state_code, state_name, state, state_full,
            country,
            pass_brands, pass_brands_json, brand,
            is_active, is_region
        ) VALUES (
            :id, :name, :slug,
            :country_code, :country_name, :country_name_override,
            :state_code, :state_name, :state, :state_full,
            :country,
            :pass_brands, :pass_brands_json, :brand,
            :is_active, :is_region
        )
    """)
    
    if dry_run:
        print("\n[DRY RUN] No changes will be made to PROD.\n")
    else:
        print("\n[LIVE RUN] Changes will be applied to PROD.\n")
    
    with prod_engine.connect() as conn:
        for resort in dev_resorts:
            resort_id = resort['id']
            resort_name = resort['name']
            
            try:
                if resort_id in prod_ids:
                    # UPDATE existing resort
                    if not dry_run:
                        conn.execute(update_sql, resort)
                    print(f"  UPDATE: ID {resort_id} - {resort_name}")
                    stats['updated'] += 1
                else:
                    # INSERT new resort
                    if not dry_run:
                        conn.execute(insert_sql, resort)
                    print(f"  INSERT: ID {resort_id} - {resort_name}")
                    stats['inserted'] += 1
                    
            except Exception as e:
                error_msg = f"ID {resort_id} - {resort_name}: {str(e)}"
                stats['errors'].append(error_msg)
                print(f"  ERROR: {error_msg}")
        
        if not dry_run:
            conn.commit()
            print("\n[COMMITTED] Changes saved to PROD database.")
    
    return stats


def check_for_duplicate_ids(resorts):
    """Check for duplicate IDs in DEV data."""
    seen = set()
    duplicates = []
    for r in resorts:
        if r['id'] in seen:
            duplicates.append(r['id'])
        seen.add(r['id'])
    return duplicates


def main():
    parser = argparse.ArgumentParser(
        description='Sync resort data from DEV to PROD database.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry run (preview changes):
    python scripts/sync_resorts_to_prod.py

  Execute sync:
    python scripts/sync_resorts_to_prod.py --confirm
        """
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Actually execute the sync (without this flag, runs in dry-run mode)'
    )
    args = parser.parse_args()
    
    dry_run = not args.confirm
    
    print("=" * 60)
    print("DEV → PROD Resort Sync")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE SYNC'}")
    print("=" * 60)
    
    # Get database URLs
    dev_url = get_env_var('DATABASE_URL')  # DEV is the default DATABASE_URL
    prod_url = get_env_var('PROD_DATABASE_URL')
    
    print(f"\nDEV Database: {dev_url[:40]}...")
    print(f"PROD Database: {prod_url[:40]}...")
    
    # Connect to databases
    print("\nConnecting to databases...")
    try:
        dev_engine = create_engine(dev_url)
        prod_engine = create_engine(prod_url)
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        sys.exit(1)
    
    # Load DEV resorts
    print("\nLoading DEV resorts...")
    dev_resorts = load_dev_resorts(dev_engine)
    
    if not dev_resorts:
        print("ERROR: No resorts found in DEV database. Aborting.")
        sys.exit(1)
    
    print(f"  Found {len(dev_resorts)} resorts in DEV")
    
    # Check for duplicate IDs
    duplicates = check_for_duplicate_ids(dev_resorts)
    if duplicates:
        print(f"ERROR: Duplicate IDs found in DEV data: {duplicates}")
        print("Aborting to prevent data corruption.")
        sys.exit(1)
    
    # Get existing PROD IDs
    print("\nLoading PROD resort IDs...")
    try:
        prod_ids = get_prod_resort_ids(prod_engine)
        print(f"  Found {len(prod_ids)} resorts in PROD")
    except Exception as e:
        print(f"ERROR: Failed to query PROD database: {e}")
        sys.exit(1)
    
    # Preview what will happen
    to_update = sum(1 for r in dev_resorts if r['id'] in prod_ids)
    to_insert = sum(1 for r in dev_resorts if r['id'] not in prod_ids)
    
    print(f"\nSync Preview:")
    print(f"  Will UPDATE: {to_update} existing resorts")
    print(f"  Will INSERT: {to_insert} new resorts")
    print(f"  Will DELETE: 0 (deletions are disabled)")
    
    if dry_run:
        print("\n" + "-" * 60)
        print("DRY RUN - No changes will be made. Pass --confirm to execute.")
        print("-" * 60)
    
    # Execute sync
    stats = sync_resorts(dev_resorts, prod_engine, prod_ids, dry_run=dry_run)
    
    # Summary
    print("\n" + "=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    print(f"  Updated: {stats['updated']}")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Errors: {len(stats['errors'])}")
    
    if stats['errors']:
        print("\nErrors encountered:")
        for err in stats['errors']:
            print(f"  - {err}")
    
    if dry_run:
        print("\n[DRY RUN COMPLETE] No changes were made.")
        print("Run with --confirm to apply changes to PROD.")
    else:
        print("\n[SYNC COMPLETE] PROD database has been updated.")
    
    print("=" * 60)


if __name__ == '__main__':
    main()
