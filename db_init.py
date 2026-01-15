"""
========================================
⚠️ DEPRECATED - DO NOT USE ⚠️
========================================

STATUS: DEPRECATED as of 2026-01-15
REASON: Supabase is now the single system of record.
        - Schema management: Use 'flask db upgrade' (Alembic migrations only)
        - Resort data: Already imported (693 resorts from prod_resorts_full.xlsx)
        - User seeding: Disabled until user migration phase

DO NOT RUN THIS SCRIPT.

========================================
ORIGINAL DOCUMENTATION (for reference):
========================================
Database initialization module.
Run with: python db_init.py
Only creates tables and ensures primary user exists.
"""

from app import app, db
from models import User


def init_database():
    """DEPRECATED: Initialize the database: create all tables and verify primary user.
    
    WARNING: db.create_all() is disabled to prevent schema drift from Alembic migrations.
    Use 'flask db upgrade' for schema management.
    """
    with app.app_context():
        # db.create_all()  # DISABLED
        print("⚠️ db.create_all() is DISABLED. Use 'flask db upgrade' instead.")
        
        primary_user = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if not primary_user:
            primary_user = User(
                first_name="Richard",
                last_name="Battle-Baxter",
                email="richardbattlebaxter@gmail.com",
                rider_type="Skier",
                pass_type="Epic",
                skill_level="Advanced",
                home_state="Colorado",
                birth_year=1985
            )
            primary_user.set_password("12345678")
            db.session.add(primary_user)
            db.session.commit()
            print("✅ PRIMARY USER CREATED: richardbattlebaxter@gmail.com")
        else:
            if not primary_user.check_password("12345678"):
                primary_user.set_password("12345678")
                db.session.commit()
                print("⚠️ PRIMARY USER PASSWORD REPAIRED: richardbattlebaxter@gmail.com")
            else:
                print(f"✅ PRIMARY USER VERIFIED: richardbattlebaxter@gmail.com (ID={primary_user.id})")
        
        print("✅ Database initialization complete")


if __name__ == "__main__":
    init_database()
