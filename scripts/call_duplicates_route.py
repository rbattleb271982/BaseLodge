import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import User

with app.app_context():
    admin_emails_str = os.environ.get("ALLOWED_ADMIN_EMAILS", "richardbattlebaxter@gmail.com,battle@battle.com")
    admin_emails = [e.strip().lower() for e in admin_emails_str.split(",") if e.strip()]

    admin_user = None
    for email in admin_emails:
        admin_user = User.query.filter(db.func.lower(User.email) == email).first()
        if admin_user:
            break

    if not admin_user:
        print("ERROR: No admin user found in the database matching ALLOWED_ADMIN_EMAILS.")
        sys.exit(1)

    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = str(admin_user.id)
            sess["_fresh"] = True

        response = client.get("/admin/resorts/duplicates")
        data = json.loads(response.data)
        print(json.dumps(data, indent=2))
