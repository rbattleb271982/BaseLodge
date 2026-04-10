#!/usr/bin/env python3
"""
One-time / idempotent import of prod_resorts_full.xlsx into local dev SQLite.

Run from project root:
    python scripts/import_dev_resorts.py

Safe to run multiple times — upserts by slug.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, generate_resort_slug
from models import db, Resort
from utils.countries import STATE_ABBR_MAP
from utils.resort_import import import_resorts_from_xlsx

XLSX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'prod_resorts_full.xlsx')

if __name__ == '__main__':
    with app.app_context():
        before = Resort.query.count()
        stats = import_resorts_from_xlsx(XLSX_PATH, db, Resort, generate_resort_slug, STATE_ABBR_MAP)
        after = Resort.query.count()
        active = Resort.query.filter_by(is_active=True).count()

    deactivated = stats.get('deactivated', 0)
    print(f"Import complete: {stats['added']} added, {stats['updated']} updated, {deactivated} deactivated")
    print(f"Total resorts in DB: {after} (was {before}), active: {active}")
