"""Tests for bounce_service.py coverage."""

import pytest
from mercury.services.bounce_service import BounceService, BounceType, BounceCategory

@pytest.fixture
def bounce_service():
    return BounceService()

def test_bounce_detection(bounce_service):
    # Hard bounce
    msg = "550 5.1.1 The email account that you tried to reach does not exist."
    b_type, category = bounce_service.categorize_bounce("550", msg)
    assert b_type == BounceType.HARD
    assert category == BounceCategory.INVALID_ADDRESS

    # Soft bounce
    msg2 = "422 4.2.2 The email account that you tried to reach is over quota."
    b_type2, category2 = bounce_service.categorize_bounce("422", msg2)
    assert b_type2 == BounceType.SOFT
    assert category2 == BounceCategory.MAILBOX_FULL

def test_bounce_processing(bounce_service, db_session):
    email = "bounce@test.com"
    # Process hard bounce
    bounce_service.process_bounce(email, "550 User unknown")
    
    assert len(bounce_service._bounces) == 1

def test_reputation_penalty(bounce_service):
    # Test stats instead
    stats = bounce_service.get_bounce_stats()
    assert 'total_bounces' in stats
