
import pytest
from datetime import datetime, UTC
from sqlalchemy import text

from mercury.data.repositories.template import TemplateRepository
from mercury.data.repositories.user import UserRepository
from mercury.data.repositories.smtp import SMTPRepository
from mercury.data.models import Template, User, SMTPServer, SMTPServerStatus

@pytest.fixture
def session(db_session):
    return db_session

class TestTemplateRepositoryExtended:
    
    def test_get_by_name(self, session):
        repo = TemplateRepository(session)
        t = Template(name="T1", html_content="C1")
        repo.create(t)
        
        found = repo.get_by_name("T1")
        assert found is not None
        assert found.html_content == "C1"
        assert repo.get_by_name("NonExistent") is None

    def test_get_active(self, session):
        repo = TemplateRepository(session)
        repo.create(Template(name="A", is_active=True))
        repo.create(Template(name="B", is_active=False))
        
        active = repo.get_active()
        assert len(active) == 1
        assert active[0].name == "A"

    def test_default_management(self, session):
        repo = TemplateRepository(session)
        t1 = repo.create(Template(name="T1", is_active=True, is_default=False))
        t2 = repo.create(Template(name="T2", is_active=True, is_default=True))
        
        # Verify initial default
        d = repo.get_default()
        assert d.name == "T2"
        
        # Set new default
        repo.set_default(t1.id)
        
        # Refresh objects
        session.refresh(t1)
        session.refresh(t2)
        
        assert t1.is_default is True
        assert t2.is_default is False
        assert repo.get_default().name == "T1"

    def test_search(self, session):
        repo = TemplateRepository(session)
        repo.create(Template(name="Welcome Email", description="Onboarding"))
        repo.create(Template(name="Reset Password", description="Security"))
        
        results = repo.search("Welcome")
        assert len(results) == 1
        assert results[0].name == "Welcome Email"
        
        results = repo.search("Security")
        assert len(results) == 1
        assert results[0].name == "Reset Password"

class TestUserRepositoryExtended:
    
    def test_get_by_lookups(self, session):
        repo = UserRepository(session)
        u = User(username="u1", email="u1@test.com", api_key="key123", is_active=True, password_hash="hash")
        repo.create(u)
        
        assert repo.get_by_username("u1") is not None
        assert repo.get_by_email("u1@test.com") is not None
        assert repo.get_by_api_key("key123") is not None
        
        assert repo.get_by_username("u2") is None
        assert repo.get_by_email("u2@test.com") is None
        assert repo.get_by_api_key("wrong") is None

    def test_get_admins(self, session):
        repo = UserRepository(session)
        repo.create(User(username="admin", is_admin=True, is_active=True, password_hash="hash"))
        repo.create(User(username="user", is_admin=False, is_active=True, password_hash="hash"))
        
        admins = repo.get_admins()
        assert len(admins) == 1
        assert admins[0].username == "admin"

    def test_existence_checks(self, session):
        repo = UserRepository(session)
        repo.create(User(username="exists", email="exists@test.com", password_hash="hash"))
        
        assert repo.username_exists("exists") is True
        assert repo.username_exists("nope") is False
        
        assert repo.email_exists("exists@test.com") is True
        assert repo.email_exists("nope@test.com") is False
        assert repo.email_exists(None) is False

class TestSMTPRepositoryExtended:
    
    def test_get_active_and_host(self, session):
        repo = SMTPRepository(session)
        s1 = repo.create(SMTPServer(name="S1", host="smtp.gmail.com", is_enabled=True, status=SMTPServerStatus.ACTIVE.value))
        s2 = repo.create(SMTPServer(name="S2", host="smtp.sendgrid.com", is_enabled=False))
        
        active = repo.get_active()
        assert len(active) == 1
        assert active[0].name == "S1"
        
        by_host = repo.get_by_host("smtp.gmail.com")
        assert len(by_host) == 1
        assert by_host[0].name == "S1"

    def test_record_success_failure_circuit(self, session):
        repo = SMTPRepository(session)
        s = repo.create(SMTPServer(name="S_Circuit", host="smtp.test.com", failure_count=0))
        
        # Test Success
        repo.record_success(s.id)
        session.refresh(s)
        assert s.total_sent == 1
        assert s.failure_count == 0
        
        # Test Failure Accumulation
        for _ in range(4):
            repo.record_failure(s.id)
        
        session.refresh(s)
        assert s.failure_count == 4
        assert s.circuit_open is False
        
        # Trip Circuit
        repo.record_failure(s.id)
        session.refresh(s)
        assert s.failure_count == 5
        assert s.circuit_open is True
        assert s.status == SMTPServerStatus.ERROR.value
        
        # Reset Circuit
        repo.reset_circuit(s.id)
        session.refresh(s)
        assert s.circuit_open is False
        assert s.failure_count == 0
        assert s.status == SMTPServerStatus.ACTIVE.value

    # test_rate_counts deleted: SMTPRepository.update_rate_counts and the
    # underlying current_minute_count / current_hour_count columns were
    # removed in migration d7a2f8e4b9c1 — rate counters are per-process
    # in-memory state on SMTPServerRuntime, never persisted.
