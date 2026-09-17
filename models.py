from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """
    One User table serves all 3 interfaces (customer/artist/admin).
    The `role` field is what decides which dashboard/permissions
    a logged-in user gets — everything else is identical.
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")  # customer / artist / admin

    def set_password(self, raw_password):
        """Hashes the password before storing — never save plain text passwords."""
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        """Compares a login attempt's password against the stored hash."""
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Track(db.Model):
    """
    A song or podcast episode. Always belongs to one artist (User).
    Customers only ever see rows where approved=True.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_podcast = db.Column(db.Boolean, default=False)
    approved = db.Column(db.Boolean, default=False)  # admin must flip this to True
    play_count = db.Column(db.Integer, default=0)
    audio_file = db.Column(db.String(300))  # filename (uploaded) or a preview URL (from API)

    artist = db.relationship("User", backref="tracks")

    def __repr__(self):
        return f"<Track {self.title} by {self.artist.username}>"


class PlayHistory(db.Model):
    """Records every time a logged-in customer plays a track, so we can show real 'recently played'."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey("track.id"), nullable=False)
    played_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User")
    track = db.relationship("Track")
