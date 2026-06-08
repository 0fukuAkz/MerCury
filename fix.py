with open("tests/test_config_dataclass_contract.py", "r") as f:
    text = f.read()

# For CampaignConfig
if "'ip_warmup_mode'" not in text:
    text = text.replace("'tracking_base_url',", "'tracking_base_url', 'ip_warmup_mode',")

# For EmailConfig
text = text.replace("'tracking_base_url',\n    'dry_run',", "'tracking_base_url', 'ip_warmup_mode',\n    'dry_run',")

# For SMTPServerConfig
text = text.replace("'priority',\n    'max_per_minute',", "'priority',\n    'max_per_minute', 'created_at_timestamp', 'total_sent_historical',")

with open("tests/test_config_dataclass_contract.py", "w") as f:
    f.write(text)
