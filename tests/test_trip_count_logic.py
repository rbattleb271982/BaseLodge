import unittest
from datetime import date, timedelta
from app import app, db, User, SkiTrip, SkiTripParticipant, get_upcoming_trip_count

class TripCountTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()
        
        # Create test user
        self.user = User(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            password_hash='dummy'
        )
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_upcoming_trip_count_logic(self):
        """
        Asserts:
        - 1 upcoming owned trip (INCLUDED)
        - 1 upcoming accepted participant trip (INCLUDED)
        - 1 past trip (EXCLUDED)
        - 1 pending invite (EXCLUDED)
        Result should be 2.
        """
        today = date.today()
        tomorrow = today + timedelta(days=1)
        yesterday = today - timedelta(days=1)
        
        # 1. Upcoming owned trip
        t1 = SkiTrip(user_id=self.user.id, mountain='Mountain 1', start_date=tomorrow, end_date=tomorrow + timedelta(days=1))
        db.session.add(t1)
        
        # 2. Upcoming accepted participant trip
        other_user = User(email='other@example.com', first_name='Other', password_hash='dummy')
        db.session.add(other_user)
        db.session.flush()
        
        t2 = SkiTrip(user_id=other_user.id, mountain='Mountain 2', start_date=tomorrow, end_date=tomorrow + timedelta(days=1))
        db.session.add(t2)
        db.session.flush()
        
        p2 = SkiTripParticipant(trip_id=t2.id, user_id=self.user.id, status='ACCEPTED')
        db.session.add(p2)
        
        # 3. Past trip
        t3 = SkiTrip(user_id=self.user.id, mountain='Mountain 3', start_date=yesterday - timedelta(days=2), end_date=yesterday)
        db.session.add(t3)
        
        # 4. Pending invite
        t4 = SkiTrip(user_id=other_user.id, mountain='Mountain 4', start_date=tomorrow, end_date=tomorrow + timedelta(days=1))
        db.session.add(t4)
        db.session.flush()
        
        p4 = SkiTripParticipant(trip_id=t4.id, user_id=self.user.id, status='INVITED')
        db.session.add(p4)
        
        db.session.commit()
        
        # Action
        count = get_upcoming_trip_count(self.user)
        
        # Assertion
        self.assertEqual(count, 2, f"Expected 2 upcoming trips, got {count}")

if __name__ == '__main__':
    unittest.main()
