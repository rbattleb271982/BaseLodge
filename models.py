from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

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


