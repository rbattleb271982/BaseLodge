"""
Database initialization module.
Run with: python db_init.py
Only creates tables and ensures primary user exists.
"""

from app import app, db
from models import User


def init_database():
    """Initialize the database: create all tables and verify primary user."""
    with app.app_context():
        db.create_all()
        
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
