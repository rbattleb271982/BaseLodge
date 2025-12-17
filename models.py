from datetime import datetime, date
from enum import Enum as PyEnum
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa

db = SQLAlchemy()


class AccommodationStatus(PyEnum):
    BOOKED = "booked"
    NOT_YET = "not_yet"
    STAYING_WITH_FRIENDS = "staying_with_friends"


class TransportationStatus(PyEnum):
    HAVE_TRANSPORT = "have_transport"
    NEED_TRANSPORT = "need_transport"
    NOT_SURE = "not_sure"


class GuestStatus(PyEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"


class EquipmentSlot(PyEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class EquipmentDiscipline(PyEnum):
    SKIER = "skier"
    SNOWBOARDER = "snowboarder"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    rider_type = db.Column(db.String(50))
    pass_type = db.Column(db.String(100))
    profile_setup_complete = db.Column(db.Boolean, default=False)
    gender = db.Column(db.String(20))
    birth_year = db.Column(db.Integer)
    home_state = db.Column(db.String(50))
    skill_level = db.Column(db.String(50))
    gear = db.Column(db.String(200))
    home_mountain = db.Column(db.String(100), nullable=True)
    mountains_visited = db.Column(db.JSON, default=list)
    open_dates = db.Column(db.JSON, default=list)  # List of YYYY-MM-DD strings
    
    trips = db.relationship('SkiTrip', backref='user', lazy=True)
    friend_requests_sent = db.relationship('Invitation', foreign_keys='Invitation.sender_id', backref='sender', lazy=True)
    friend_requests_received = db.relationship('Invitation', foreign_keys='Invitation.receiver_id', backref='receiver', lazy=True)
    friends = db.relationship('Friend', foreign_keys='Friend.user_id', backref='user_obj', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'


class Resort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(2), nullable=False)  # Abbreviation: CO, CA, etc.
    state_full = db.Column(db.String(50), nullable=True)  # Full name: Colorado, California, etc.
    brand = db.Column(db.String(20), nullable=True)  # 'Epic', 'Ikon', 'Indy', 'Other'
    pass_brands = db.Column(db.String(150), nullable=True)  # Comma-separated: 'Epic', 'Ikon,MountainCollective', etc.
    slug = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    trips = db.relationship('SkiTrip', backref='resort', lazy=True)

    def __repr__(self):
        return f'<Resort {self.name} ({self.state})>'


class SkiTrip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resort_id = db.Column(db.Integer, db.ForeignKey('resort.id'), nullable=True)
    state = db.Column(db.String(50))  # Kept for backward compatibility
    mountain = db.Column(db.String(100))  # Kept for backward compatibility
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    pass_type = db.Column(db.String(50), default="No Pass")
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SkiTrip {self.mountain}>'


class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    friend = db.relationship('User', foreign_keys=[friend_id], backref='friended_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),)

    def __repr__(self):
        return f'<Friend {self.user_id} -> {self.friend_id}>'


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, declined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('sender_id', 'receiver_id', name='unique_invitation'),)

    def __repr__(self):
        return f'<Invitation {self.sender_id} -> {self.receiver_id}>'


class InviteToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    inviter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at = db.Column(db.DateTime, nullable=True)
    max_uses = db.Column(db.Integer, default=5)  # Max 5 accepts per token
    uses_count = db.Column(db.Integer, default=0)  # Current usage count
    expires_at = db.Column(db.DateTime, nullable=True)  # Token expiration

    inviter = db.relationship("User", backref="invite_tokens")

    def is_expired(self):
        """Check if token has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def is_fully_used(self):
        """Check if token has reached max uses."""
        return self.uses_count >= self.max_uses

    def __repr__(self):
        return f'<InviteToken {self.token[:8]}... by user {self.inviter_id}>'


class GroupTrip(db.Model):
    """Shared/social trip with host and guests."""
    __tablename__ = 'group_trip'
    
    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    accommodation_status = db.Column(
        db.Enum(AccommodationStatus, name='accommodation_status_enum', create_constraint=True),
        nullable=True
    )
    transportation_status = db.Column(
        db.Enum(TransportationStatus, name='transportation_status_enum', create_constraint=True),
        nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    host = db.relationship('User', backref='hosted_trips', foreign_keys=[host_id])
    
    def __repr__(self):
        return f'<GroupTrip {self.id}: {self.title or "Untitled"}>'


class TripGuest(db.Model):
    """Join table for users invited to group trips."""
    __tablename__ = 'trip_guest'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('group_trip.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(
        db.Enum(GuestStatus, name='guest_status_enum', create_constraint=True),
        default=GuestStatus.INVITED,
        nullable=False
    )
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    trip = db.relationship('GroupTrip', backref='guests')
    user = db.relationship('User', backref='trip_memberships')
    
    __table_args__ = (
        db.UniqueConstraint('trip_id', 'user_id', name='unique_trip_guest'),
    )
    
    def __repr__(self):
        return f'<TripGuest trip={self.trip_id} user={self.user_id} status={self.status.value}>'


class EquipmentSetup(db.Model):
    """Profile-level gear setup (max 2 per user: primary + secondary)."""
    __tablename__ = 'equipment_setup'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot = db.Column(
        db.Enum(EquipmentSlot, name='equipment_slot_enum', create_constraint=True),
        nullable=False
    )
    discipline = db.Column(
        db.Enum(EquipmentDiscipline, name='equipment_discipline_enum', create_constraint=True),
        nullable=False
    )
    brand = db.Column(db.String(100), nullable=True)
    length_cm = db.Column(db.Integer, nullable=True)
    width_mm = db.Column(db.Integer, nullable=True)
    
    user = db.relationship('User', backref='equipment_setups')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'slot', name='unique_user_equipment_slot'),
    )
    
    def __repr__(self):
        return f'<EquipmentSetup user={self.user_id} slot={self.slot.value} discipline={self.discipline.value}>'


def check_shared_upcoming_trip(user_a_id: int, user_b_id: int) -> bool:
    """
    Check if two users share at least one accepted, upcoming group trip.
    
    Args:
        user_a_id: ID of the first user
        user_b_id: ID of the second user
    
    Returns:
        True if both users are accepted guests on the same trip with dates >= today
    """
    today = date.today()
    
    user_a_trips = db.session.query(TripGuest.trip_id).filter(
        TripGuest.user_id == user_a_id,
        TripGuest.status == GuestStatus.ACCEPTED
    ).subquery()
    
    user_b_trips = db.session.query(TripGuest.trip_id).filter(
        TripGuest.user_id == user_b_id,
        TripGuest.status == GuestStatus.ACCEPTED
    ).subquery()
    
    shared_trip = db.session.query(GroupTrip).filter(
        GroupTrip.id.in_(sa.select(user_a_trips)),
        GroupTrip.id.in_(sa.select(user_b_trips)),
        GroupTrip.end_date >= today
    ).first()
    
    return shared_trip is not None


