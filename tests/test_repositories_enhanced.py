"""Enhanced tests for data repositories."""

import pytest
from unittest.mock import Mock, MagicMock
from sqlalchemy.orm import Session
from datetime import datetime
from unified_sender.data.repositories.recipient import RecipientRepository, RecipientListRepository
from unified_sender.data.repositories.campaign import CampaignRepository
from unified_sender.data.repositories.smtp import SMTPRepository
from unified_sender.data.models import (
    Recipient, RecipientList, RecipientStatus, 
    Campaign, CampaignStatus,
    SMTPServer, SMTPServerStatus
)

@pytest.fixture
def mock_session():
    return MagicMock(spec=Session)

@pytest.fixture
def recipient_repo(mock_session):
    return RecipientRepository(mock_session)

@pytest.fixture
def list_repo(mock_session):
    return RecipientListRepository(mock_session)

@pytest.fixture
def campaign_repo(mock_session):
    return CampaignRepository(mock_session)

@pytest.fixture
def smtp_repo(mock_session):
    return SMTPRepository(mock_session)

# --- RecipientRepository Tests ---

def test_get_by_email(recipient_repo, mock_session):
    email = "test@example.com"
    mock_result = Mock()
    mock_session.execute.return_value = mock_result
    mock_result.scalar_one_or_none.return_value = Recipient(email=email)
    
    result = recipient_repo.get_by_email(email)
    
    assert result.email == email
    mock_session.execute.assert_called_once()
    args = mock_session.execute.call_args[0]
    stmt_str = str(args[0])
    assert "recipient" in stmt_str.lower()

def test_get_pending_by_list(recipient_repo, mock_session):
    mock_result = Mock()
    mock_session.execute.return_value = mock_result
    r1 = Recipient(email="1@t.com", status=RecipientStatus.PENDING.value)
    mock_result.scalars.return_value = [r1]
    
    result = recipient_repo.get_pending_by_list(list_id=1, limit=10)
    
    assert len(result) == 1
    assert result[0] == r1
    args = mock_session.execute.call_args[0]
    stmt_str = str(args[0])
    assert "LIMIT" in stmt_str

def test_iterate_by_list_pending(recipient_repo, mock_session):
    mock_result1 = Mock()
    mock_result1.scalars.return_value = [Recipient(id=1)]
    mock_result2 = Mock()
    mock_result2.scalars.return_value = [] 
    
    mock_session.execute.side_effect = [mock_result1, mock_result2]
    
    batches = list(recipient_repo.iterate_by_list(list_id=1, batch_size=1, pending_only=True))
    
    assert len(batches) == 1
    assert len(batches[0]) == 1
    # Logic in iterate_by_list implies 1 call for pending_only
    assert mock_session.execute.call_count == 1

def test_bulk_update_status(recipient_repo, mock_session):
    r1 = Recipient(id=1, status='pending')
    r2 = Recipient(id=2, status='pending')
    
    mock_result = Mock()
    mock_result.scalars.return_value = [r1, r2]
    mock_session.execute.return_value = mock_result
    
    recipient_repo.bulk_update_status([1, 2], RecipientStatus.SENT)
    
    assert r1.status == RecipientStatus.SENT.value
    assert r2.status == RecipientStatus.SENT.value
    mock_session.commit.assert_called_once()

def test_count_by_status(recipient_repo, mock_session):
    mock_result = Mock()
    mock_result.all.return_value = [('pending', 10), ('sent', 5)]
    mock_session.execute.return_value = mock_result
    
    counts = recipient_repo.count_by_status(list_id=1)
    
    assert counts['pending'] == 10
    assert counts['sent'] == 5

def test_suppress_email(recipient_repo, mock_session):
    r1 = Recipient(email="t@e.com", is_suppressed=False)
    mock_result = Mock()
    mock_result.scalars.return_value = [r1]
    mock_session.execute.return_value = mock_result
    
    recipient_repo.suppress_email("t@e.com")
    
    assert r1.is_suppressed is True
    assert r1.status == RecipientStatus.SUPPRESSED.value
    mock_session.commit.assert_called_once()

def test_bulk_create(recipient_repo, mock_session):
    recipients = [Recipient(email="1"), Recipient(email="2")]
    count = recipient_repo.bulk_create(recipients)
    assert count == 2
    mock_session.add_all.assert_called_with(recipients)
    mock_session.commit.assert_called_once()

# --- RecipientListRepository Tests ---

def test_list_get_by_name(list_repo, mock_session):
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = RecipientList(name="L1")
    mock_session.execute.return_value = mock_result
    
    res = list_repo.get_by_name("L1")
    assert res.name == "L1"
    args = mock_session.execute.call_args[0]
    assert "recipientlists" in str(args[0]).lower()

# --- CampaignRepository Tests ---

def test_campaign_get_active(campaign_repo, mock_session):
    mock_result = Mock()
    c1 = Campaign(name="C1", status=CampaignStatus.SENDING)
    mock_result.scalars.return_value = [c1]
    mock_session.execute.return_value = mock_result
    
    res = campaign_repo.get_active()
    assert len(res) == 1
    assert res[0] == c1
    mock_session.execute.assert_called()

def test_campaign_search(campaign_repo, mock_session):
    mock_result = Mock()
    c1 = Campaign(name="Found")
    mock_result.scalars.return_value = [c1]
    mock_session.execute.return_value = mock_result
    
    res = campaign_repo.search("Found")
    assert len(res) == 1
    assert res[0].name == "Found"
    args = mock_session.execute.call_args[0]
    assert "LIKE" in str(args[0]) or "ilike" in str(args[0]).lower()

def test_campaign_increment_counters(campaign_repo, mock_session):
    # Initialize counters to 0 to avoid TypeError on +=
    c1 = Campaign(id=1, sent_count=0, delivered_count=0, failed_count=0)
    mock_session.get.return_value = c1
    
    campaign_repo.increment_counters(1, sent=10, delivered=5)
    
    assert c1.sent_count == 10
    assert c1.delivered_count == 5
    mock_session.commit.assert_called_once()

def test_campaign_update_status(campaign_repo, mock_session):
    c1 = Campaign(id=1, status=CampaignStatus.DRAFT)
    mock_session.get.return_value = c1
    
    campaign_repo.update_status(1, CampaignStatus.PAUSED)
    
    assert c1.status == CampaignStatus.PAUSED
    mock_session.commit.assert_called_once()

# --- SMTPRepository Tests ---

def test_smtp_get_active(smtp_repo, mock_session):
    mock_result = Mock()
    s1 = SMTPServer(host="smtp", status=SMTPServerStatus.ACTIVE.value)
    mock_result.scalars.return_value = [s1]
    mock_session.execute.return_value = mock_result
    
    res = smtp_repo.get_active()
    assert len(res) == 1
    assert res[0] == s1

def test_smtp_record_success_clears_circuit(smtp_repo, mock_session):
    # Initialize counters to 0
    s1 = SMTPServer(id=1, failure_count=5, circuit_open=True, total_sent=0)
    mock_session.get.return_value = s1
    
    smtp_repo.record_success(1)
    
    assert s1.total_sent == 1
    assert s1.failure_count == 0
    assert s1.circuit_open is False
    mock_session.commit.assert_called_once()

def test_smtp_record_failure_trips_circuit(smtp_repo, mock_session):
    # Pre-condition: 4 failures
    s1 = SMTPServer(id=1, failure_count=4, circuit_open=False, total_failed=0)
    mock_session.get.return_value = s1
    
    smtp_repo.record_failure(1, "Error")
    
    # Post-condition: 5 failures, circuit open
    assert s1.failure_count == 5
    assert s1.circuit_open is True
    assert s1.status == SMTPServerStatus.ERROR.value
    mock_session.commit.assert_called_once()

def test_smtp_reset_circuit(smtp_repo, mock_session):
    s1 = SMTPServer(id=1, circuit_open=True, failure_count=10)
    mock_session.get.return_value = s1
    
    smtp_repo.reset_circuit(1)
    
    assert s1.circuit_open is False
    assert s1.failure_count == 0
    assert s1.status == SMTPServerStatus.ACTIVE.value
    mock_session.commit.assert_called_once()
