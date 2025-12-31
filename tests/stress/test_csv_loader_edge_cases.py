
import pytest
import csv
import os
from unified_sender.services.campaign_service import CampaignService

def test_csv_loader_case_mismatch(tmp_path):
    """
    Bug Hunt: Does loader silently skip rows if header case doesn't match?
    """
    csv_file = tmp_path / "recipients.csv"
    # Header is 'Email', but default loader looks for 'email'
    content = "Email,Name\ntest@example.com,Test User"
    csv_file.write_text(content, encoding='utf-8')
    
    service = CampaignService()
    
    # By default email_column='email'
    recipients = list(service.load_recipients_from_csv(str(csv_file)))
    
    # If this is empty, it's a UX bug (silent failure)
    # Ideally it should either work (nocase) or warn?
    # For now, let's see if it fails.
    if len(recipients) == 0:
        pytest.fail("Loader silently skipped rows due to case mismatch in header ('Email' vs 'email')")

def test_csv_loader_bom_handling(tmp_path):
    """
    Ensure utf-8-sig (BOM) is handled correctly.
    """
    csv_file = tmp_path / "recipients_bom.csv"
    content = "email,name\ntest@example.com,Test"
    # Write with BOM
    with open(csv_file, 'w', encoding='utf-8-sig') as f:
        f.write(content)
        
    service = CampaignService()
    recipients = list(service.load_recipients_from_csv(str(csv_file)))
    
    assert len(recipients) == 1
    assert recipients[0]['email'] == 'test@example.com'

def test_csv_missing_column(tmp_path):
    """
    What if the email column is entirely missing?
    """
    csv_file = tmp_path / "bad.csv"
    content = "name,phone\nJohn,123"
    csv_file.write_text(content, encoding='utf-8')
    
    service = CampaignService()
    recipients = list(service.load_recipients_from_csv(str(csv_file)))
    
    # Should probably be empty, but is it silent?
    assert len(recipients) == 0

def test_csv_malformed_lines(tmp_path):
    """
    CSV with ragged rows.
    """
    csv_file = tmp_path / "ragged.csv"
    content = "email,name\nvalid@example.com,Valid\nbroken_row"
    csv_file.write_text(content, encoding='utf-8')
    
    service = CampaignService()
    recipients = list(service.load_recipients_from_csv(str(csv_file)))
    
    # Readers usually handle valid rows and maybe error on broken ones
    # We want to ensure at least the valid one is loaded
    assert len(recipients) >= 1
    assert recipients[0]['email'] == 'valid@example.com'
