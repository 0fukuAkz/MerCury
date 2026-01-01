"""Authentication routes."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from ...security.auth import authenticate

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login page and authentication handler.
    
    GET: Display login form
    POST: Process login credentials and authenticate user
    """
    # Note: 'index' endpoint is in views blueprint, assume it will be registered
    if current_user.is_authenticated:
        return redirect(url_for('views.index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        user = authenticate(username, password)
        
        if user:
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash('Logged in successfully.', 'success')
            # Check if next_page is safe or just redirect to index
            return redirect(next_page or url_for('views.index'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """Logout current user and end session."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
