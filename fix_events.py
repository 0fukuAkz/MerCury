with open("src/mercury/web/events.py", "r") as f:
    text = f.read()

text = text.replace("from ..data.database import get_session_direct", "from ..data.database import session_scope")
text = text.replace("            session = get_session_direct()\n            try:\n                repo = CampaignRepository(session)\n                campaign = repo.get(campaign_id)\n                if campaign:\n                    campaign.status = CampaignStatus.CANCELLED\n                    campaign.completed_at = datetime.now(UTC)\n                    repo.update(campaign)\n            finally:\n                session.close()", "            with session_scope() as session:\n                repo = CampaignRepository(session)\n                campaign = repo.get(campaign_id)\n                if campaign:\n                    campaign.status = CampaignStatus.CANCELLED\n                    campaign.completed_at = datetime.now(UTC)\n                    repo.update(campaign)")
with open("src/mercury/web/events.py", "w") as f:
    f.write(text)
