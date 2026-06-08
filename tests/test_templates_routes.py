"""Tests for templates routes."""

import pytest


def test_templates_index_unauthenticated(client):
    """Test templates dashboard redirects if not logged in."""
    response = client.get("/templates/")
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


def test_templates_index_authenticated(client, db_session):
    """Test templates dashboard loads for logged in users."""
    # Since we use flask-login, we need to mock or use test_client session
    # We can inject a mock user or use the admin_user fixture but we need to log them in
    # For now, let's patch login_required to bypass it for tests, or use the client with session
    # Actually, simpler is to use a mocked test client that is logged in.
    pass  # Tested elsewhere or requires complex setup. Let's do a direct login simulation.


@pytest.fixture
def logged_in_client(client, admin_user):
    """Log in the test client."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_user.id)
        sess["_fresh"] = True
    return client


def test_templates_index_loads(logged_in_client):
    """Templates dashboard loads successfully."""
    response = logged_in_client.get("/templates/")
    assert response.status_code == 200


def test_template_save_new(logged_in_client, db_session):
    """Test creating a new template."""
    response = logged_in_client.post(
        "/templates/save",
        data={
            "name": "Welcome Template",
            "subject": "Welcome to our platform",
            "html_content": "<h1>Hello!</h1>",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Template created successfully" in response.data

    from mercury.data.models import Template

    template = db_session.query(Template).filter_by(name="Welcome Template").first()
    assert template is not None
    assert template.subject == "Welcome to our platform"


def test_template_save_update(logged_in_client, db_session):
    """Test updating an existing template."""
    from mercury.data.models import Template

    t = Template(name="Old Name", subject="Old Subj", html_content="old", is_active=True)
    db_session.add(t)
    db_session.commit()

    response = logged_in_client.post(
        "/templates/save",
        data={
            "template_id": str(t.id),
            "name": "Updated Name",
            "subject": "Updated Subj",
            "html_content": "updated html",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Template updated successfully" in response.data

    db_session.refresh(t)
    assert t.name == "Updated Name"
    assert t.subject == "Updated Subj"
    assert t.html_content == "updated html"


def test_template_save_missing_name(logged_in_client):
    """Test save fails without name."""
    response = logged_in_client.post(
        "/templates/save", data={"name": "", "subject": "Testing"}, follow_redirects=True
    )

    assert response.status_code == 200
    assert b"Template name is required" in response.data


def test_template_toggle(logged_in_client, db_session):
    """Test toggling template active status."""
    from mercury.data.models import Template

    t = Template(name="Toggle Me", subject="Subj", html_content="html", is_active=True)
    db_session.add(t)
    db_session.commit()

    response = logged_in_client.post(f"/templates/{t.id}/toggle", follow_redirects=True)
    assert response.status_code == 200
    assert b"deactivated" in response.data

    db_session.refresh(t)
    assert t.is_active is False


def test_template_delete(logged_in_client, db_session):
    """Test deleting a template."""
    from mercury.data.models import Template

    t = Template(name="Delete Me", subject="Subj", html_content="html", is_active=True)
    db_session.add(t)
    db_session.commit()

    tid = t.id
    response = logged_in_client.post(f"/templates/{tid}/delete", follow_redirects=True)
    assert response.status_code == 200
    assert b"Template deleted" in response.data

    deleted = db_session.query(Template).filter_by(id=tid).first()
    assert deleted is None
