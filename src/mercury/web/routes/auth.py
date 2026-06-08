"""Authentication routes."""

from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from ...security.auth import authenticate
from ..extensions import limiter

auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect(url: str) -> bool:
    """Verify the redirect URL is relative to prevent open redirects."""
    if not url:
        return True
    parsed = urlparse(url)
    return not parsed.netloc and not parsed.scheme


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5/minute", exempt_when=lambda: request.method == "GET")
def login():
    """
    User login page and authentication handler.

    GET: Display login form
    POST: Process login credentials and authenticate user
    """
    # Note: 'index' endpoint is in views blueprint, assume it will be registered
    if current_user.is_authenticated:
        return redirect(url_for("views.index"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        remember = request.form.get("remember", False)

        user = authenticate(username, password)

        if user:
            login_user(user, remember=remember)
            next_page = request.args.get("next")
            flash("Logged in successfully.", "success")

            # Check if next_page is safe or just redirect to index
            if next_page and _is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(url_for("views.index"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Logout current user and end session."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
