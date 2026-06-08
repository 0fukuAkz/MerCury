from sqlalchemy import text


def test_schema_has_ip_warmup(db_session):
    result = db_session.execute(text("PRAGMA table_info(smtpservers)")).fetchall()
    columns = [row[1] for row in result]
    print("\nCOLUMNS:", columns)
    assert "ip_warmup" in columns
