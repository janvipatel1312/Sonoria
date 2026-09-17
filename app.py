from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Track, PlayHistory
import requests

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-this-to-something-random"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form.get("role", "customer")  # only customer/artist allowed from this form

        if role == "admin":
            return "Admin accounts cannot be created through signup", 403

        if User.query.filter_by(username=username).first():
            return "Username already taken"

        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        return "Invalid username or password"

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
def home():
    """
    YT Music-style homepage:
    - Logged-in customer with history -> their Recently Played
    - New/logged-out user -> Trending Now instead
    - Always shows: Trending row, Viral-on-Shorts row, singer selector
    """
    recently_played = []
    if current_user.is_authenticated:
        history = (PlayHistory.query
                   .filter_by(user_id=current_user.id)
                   .order_by(PlayHistory.played_at.desc())
                   .limit(10).all())
        # de-duplicate by track, keep most recent play of each
        seen = set()
        for h in history:
            if h.track_id not in seen:
                recently_played.append(h.track)
                seen.add(h.track_id)

    trending = (Track.query.filter_by(approved=True)
                .order_by(Track.play_count.desc()).limit(10).all())

    viral_shorts = (Track.query.filter_by(approved=True)
                     .order_by(Track.id.desc()).limit(10).all())

    # Singer selector: distinct artists who have at least one approved track
    singer_ids = (db.session.query(Track.artist_id)
                  .filter_by(approved=True).distinct().all())
    singers = [db.session.get(User, sid[0]) for sid in singer_ids]

    return render_template(
        "home.html",
        recently_played=recently_played,
        trending=trending,
        viral_shorts=viral_shorts,
        singers=singers,
    )


@app.route("/play/<int:track_id>")
def play_track(track_id):
    """Logs a play (if logged in) and increments the track's global play count."""
    track = db.session.get(Track, track_id)
    if not track:
        return "Track not found", 404

    track.play_count += 1
    if current_user.is_authenticated:
        db.session.add(PlayHistory(user_id=current_user.id, track_id=track.id))
    db.session.commit()

    return redirect(url_for("home"))


@app.route("/artist/<int:artist_id>")
def artist_page(artist_id):
    """Singer selector click-through: shows all approved tracks by one artist."""
    artist = db.session.get(User, artist_id)
    if not artist or artist.role != "artist":
        return "Artist not found", 404
    tracks = Track.query.filter_by(artist_id=artist_id, approved=True).all()
    return render_template("artist_page.html", artist=artist, tracks=tracks)


@app.route("/search")
def search():
    """Audio-only search using the iTunes API - no API key needed, 30-second previews."""
    query = request.args.get("q", "").strip()
    results = []
    error = None

    if query:
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={"term": query, "media": "music", "limit": 15},
                timeout=5
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except requests.RequestException:
            error = "Could not reach the music search service right now. Try again shortly."

    return render_template("search.html", results=results, query=query, error=error)


import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB limit


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/artist/dashboard")
@login_required
def artist_dashboard():
    if current_user.role != "artist":
        return "Not authorized", 403
    my_tracks = Track.query.filter_by(artist_id=current_user.id).order_by(Track.id.desc()).all()
    return render_template("artist_dashboard.html", tracks=my_tracks)


@app.route("/artist/upload", methods=["GET", "POST"])
@login_required
def upload_track():
    if current_user.role != "artist":
        return "Not authorized", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        file = request.files.get("audio_file")

        if not title:
            return render_template("upload.html", error="Title is required.")

        if not file or file.filename == "":
            return render_template("upload.html", error="Please choose an audio file.")

        if not allowed_file(file.filename):
            return render_template("upload.html", error="Only mp3, wav, or m4a files are allowed.")

        filename = secure_filename(file.filename)
        file.save(os.path.join(UPLOAD_FOLDER, filename))

        track = Track(title=title, artist_id=current_user.id, audio_file=filename)
        db.session.add(track)
        db.session.commit()
        return redirect(url_for("artist_dashboard"))

    return render_template("upload.html", error=None)


def is_admin(user):
    return user.is_authenticated and user.role == "admin"


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if not is_admin(current_user):
        return "Not authorized", 403

    total_users = User.query.count()
    total_tracks = Track.query.count()
    pending_count = Track.query.filter_by(approved=False).count()

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_tracks=total_tracks,
        pending_count=pending_count,
    )


@app.route("/admin/approve")
@login_required
def admin_approve():
    if not is_admin(current_user):
        return "Not authorized", 403
    pending_tracks = Track.query.filter_by(approved=False).all()
    return render_template("admin_approve.html", tracks=pending_tracks)


@app.route("/admin/approve/<int:track_id>")
@login_required
def approve_track(track_id):
    if not is_admin(current_user):
        return "Not authorized", 403
    track = db.session.get(Track, track_id)
    if not track:
        return "Track not found", 404
    track.approved = True
    db.session.commit()
    return redirect(url_for("admin_approve"))


@app.route("/admin/reject/<int:track_id>")
@login_required
def reject_track(track_id):
    if not is_admin(current_user):
        return "Not authorized", 403
    track = db.session.get(Track, track_id)
    if not track:
        return "Track not found", 404
    db.session.delete(track)
    db.session.commit()
    return redirect(url_for("admin_approve"))


@app.route("/dashboard")
@login_required
def dashboard():
    # Temporary placeholder - each role gets its own real dashboard later
    return f"Logged in as {current_user.username} (role: {current_user.role})"


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
