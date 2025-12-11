from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
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
    mountains_visited = db.Column(db.JSON, default=[])
    
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


class SkiTrip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    state = db.Column(db.String(50))
    mountain = db.Column(db.String(100))
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
