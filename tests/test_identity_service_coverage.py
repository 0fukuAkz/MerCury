"""Tests for identity_service.py coverage."""

import pytest
from unittest.mock import patch
from mercury.services.identity_service import IdentityService
from mercury.data.models.identity import FromEmail, SenderName


@pytest.fixture(autouse=True)
def setup_db(db_session):
    with patch("mercury.services.identity_service.get_session_direct", return_value=db_session):
        db_session.query(FromEmail).delete()
        db_session.query(SenderName).delete()
        db_session.commit()
        yield


@pytest.fixture
def identity_service(db_session):
    # We must patch get_session_direct in the module where it's used
    with patch("mercury.services.identity_service.get_session_direct", return_value=db_session):
        yield IdentityService()


def test_identity_add_email(identity_service, db_session):
    email = "test@example.com"
    # Test adding new
    res = identity_service.add_email(email, tags=["t1"])
    assert res.email == email
    assert "t1" in res.tags

    # Test adding existing
    res2 = identity_service.add_email(email)
    assert res2.id == res.id


def test_identity_add_name(identity_service, db_session):
    name = "Sender One"
    res = identity_service.add_name(name, tags=["tag1"])
    assert res.name == name
    assert "tag1" in res.tags


def test_identity_get_methods(identity_service, db_session):
    # Clear any existing
    db_session.query(FromEmail).delete()
    db_session.query(SenderName).delete()
    db_session.commit()

    identity_service.add_email("active@test.com")
    e2 = identity_service.add_email("inactive@test.com")
    identity_service.toggle_email_status(e2.id)

    emails = identity_service.get_emails(active_only=True)
    assert len(emails) == 1
    assert emails[0].email == "active@test.com"

    names = identity_service.get_names()
    assert len(names) == 0  # None added yet


def test_identity_toggle_and_delete(db_session):
    e = IdentityService.add_email("toggle@test.com")
    fixed_e = IdentityService.toggle_email_status(e.id)
    assert fixed_e.is_active is False

    assert IdentityService.delete_email(e.id) is True
    assert IdentityService.delete_email(9999) is False

    n = IdentityService.add_name("NameToDelete")
    assert IdentityService.delete_name(n.id) is True
    assert IdentityService.delete_name(8888) is False


def test_identity_random_selection(db_session):
    db_session.query(FromEmail).delete()
    db_session.query(SenderName).delete()
    db_session.commit()

    IdentityService.add_email("e1@t.com", tags=["tagA"])
    IdentityService.add_name("N1", tags=["tagB"])

    # Selection with tag
    email, name = IdentityService.get_random_identity(tag="tagA")
    assert email == "e1@t.com"
    # Name pool has "N1" with "tagB", so tagA selection for name falls back to all active
    assert name == "N1"

    # Selection without tag
    email2, name2 = IdentityService.get_random_identity()
    assert email2 == "e1@t.com"
    assert name2 == "N1"
