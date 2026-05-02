"""Tests for code added during the recent hardening pass.

Covers:
- ``mercury.web.decorators.api_key_required`` (automation-only auth gate).
- ``mercury.data.database.session_scope`` (rollback-on-exception helper).
- ``mercury.data.repositories.base.BaseRepository.bulk_create``.
"""

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, jsonify

from mercury.data.database import session_scope
from mercury.data.repositories.base import BaseRepository
from mercury.web.decorators import api_key_required


def _make_app(view):
    app = Flask(__name__)
    app.add_url_rule('/protected', view_func=api_key_required(view), methods=['GET'])
    return app


def test_api_key_required_accepts_valid_key():
    with patch('mercury.web.decorators.require_api_key', return_value=True):
        app = _make_app(lambda: jsonify({'ok': True}))
        client = app.test_client()
        resp = client.get('/protected', headers={'X-API-Key': 'good-key'})
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True


def test_api_key_required_rejects_missing_key():
    app = _make_app(lambda: jsonify({'ok': True}))
    client = app.test_client()
    resp = client.get('/protected')
    assert resp.status_code == 401
    assert 'X-API-Key' in resp.get_json()['error']


def test_api_key_required_rejects_invalid_key():
    with patch('mercury.web.decorators.require_api_key', return_value=False):
        app = _make_app(lambda: jsonify({'ok': True}))
        client = app.test_client()
        resp = client.get('/protected', headers={'X-API-Key': 'bad-key'})
        assert resp.status_code == 401


def test_session_scope_closes_session_on_success():
    fake_session = MagicMock()
    with patch('mercury.data.database.get_session_direct', return_value=fake_session):
        with session_scope() as s:
            assert s is fake_session
    fake_session.close.assert_called_once()
    fake_session.rollback.assert_not_called()


def test_session_scope_rolls_back_and_closes_on_exception():
    fake_session = MagicMock()
    with patch('mercury.data.database.get_session_direct', return_value=fake_session):
        with pytest.raises(RuntimeError, match="boom"):
            with session_scope():
                raise RuntimeError("boom")
    fake_session.rollback.assert_called_once()
    fake_session.close.assert_called_once()


def test_session_scope_swallows_rollback_failure():
    """If rollback itself raises, the original exception still propagates."""
    fake_session = MagicMock()
    fake_session.rollback.side_effect = RuntimeError("rollback also failed")
    with patch('mercury.data.database.get_session_direct', return_value=fake_session):
        with pytest.raises(ValueError, match="original"):
            with session_scope():
                raise ValueError("original")
    fake_session.close.assert_called_once()


def test_bulk_create_empty_list_is_noop():
    fake_session = MagicMock()

    class Dummy:
        pass

    repo = BaseRepository(fake_session, Dummy)
    assert repo.bulk_create([]) == 0
    fake_session.add_all.assert_not_called()
    fake_session.commit.assert_not_called()


def test_bulk_create_inserts_and_commits():
    fake_session = MagicMock()

    class Dummy:
        pass

    repo = BaseRepository(fake_session, Dummy)
    entities = [Dummy(), Dummy(), Dummy()]
    assert repo.bulk_create(entities) == 3
    fake_session.add_all.assert_called_once_with(entities)
    fake_session.commit.assert_called_once()
