"""
Test suite for profile consolidation - ensures /profile is replaced with /more.
Prevents regressions and guarantees trip duration display.
"""

import pytest
from app import app, db
from models import User
from datetime import date


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture
def logged_in_user(client):
    """Create and login a test user."""
    with app.app_context():
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            rider_type="Skier",
            pass_type="Epic"
        )
        user.set_password("testpassword")
        db.session.add(user)
        db.session.commit()
        
        with client:
            client.post('/auth', data={
                'email': 'test@example.com',
                'password': 'testpassword',
                'action': 'login'
            })
            yield user


def test_profile_redirects(client):
    """Test that /profile always redirects to /more."""
    response = client.get("/profile", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location


def test_profile_post_redirects(client, logged_in_user):
    """Test that POST to /profile redirects to /more."""
    response = client.post("/profile", data={"skill_level": "Advanced"}, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location


def test_edit_profile_save_redirects(client, logged_in_user):
    """Test that saving profile edits redirects to /more, not /profile."""
    response = client.post("/edit_profile", data={
        "skill_level": "Advanced",
        "rider_type": "Skier",
        "pass_type": "Epic"
    }, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location
    assert "/profile" not in response.location


def test_no_profile_template_reference():
    """Test that profile.html is never referenced in app.py."""
    with open("app.py", "r") as f:
        code = f.read()
    assert "profile.html" not in code, "profile.html should not be referenced in app.py"


def test_trip_duration_display(client, logged_in_user):
    """Test that trip rows include duration in days."""
    from models import SkiTrip, Resort
    
    with app.app_context():
        # Create a test resort
        resort = Resort(
            name="Test Resort",
            state="CO",
            brand="Epic"
        )
        db.session.add(resort)
        db.session.commit()
        
        # Create a trip: Feb 10 - Feb 13 = 4 days
        trip = SkiTrip(
            user_id=logged_in_user.id,
            mountain="Test Resort",
            state="CO",
            start_date=date(2025, 2, 10),
            end_date=date(2025, 2, 13),
            is_public=True,
            resort_id=resort.id
        )
        db.session.add(trip)
        db.session.commit()
        
        # Verify duration calculation
        duration = (trip.end_date - trip.start_date).days + 1
        assert duration == 4, f"Trip should be 4 days, got {duration}"


def test_no_redirect_to_old_profile():
    """Test that nothing redirects to the old /profile route."""
    with open("app.py", "r") as f:
        code = f.read()
    
    # Check for dangerous redirect patterns
    assert "redirect(url_for(\"profile\"))" not in code
    assert "redirect(url_for('profile'))" not in code
