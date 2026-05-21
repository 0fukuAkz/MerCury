"""Placeholders API.

Two surfaces in one resource:
1. ``GET  /api/placeholders``    — combined catalog: built-ins + custom.
2. ``GET  /api/placeholders/custom``    — custom rows only (list).
3. ``POST /api/placeholders/custom``    — create.
4. ``PUT  /api/placeholders/custom/<id>`` — update.
5. ``DELETE /api/placeholders/custom/<id>`` — delete.

The combined GET is what the admin page loads — one fetch, one render.
Custom mutations are kept under ``/custom/...`` so the route shape
mirrors the surface: built-ins are *defined by code*, not by API.
"""
import re

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
    CustomPlaceholderRepository,
)
from ....data.models import CustomPlaceholder
from ....features.placeholders import PlaceholderProcessor


# Restrictive on purpose: substitution-key syntax is `{{<name>}}`, and the
# regex engine accepts a-z/0-9/_/. — allowing operators to define names
# like "company:logo" would resolve to literal text at render time.
_NAME_RE = re.compile(r'^[a-z][a-z0-9_.]{0,79}$')


def _validate_name(name: str) -> str | None:
    """Returns an error string on invalid name, None on valid."""
    if not name:
        return 'name is required'
    if not _NAME_RE.match(name):
        return (
            "name must start with a lowercase letter and contain only "
            "lowercase letters, digits, '_' or '.' (max 80 chars)"
        )
    return None


@api_bp.route('/placeholders', methods=['GET'])
@api_key_or_login_required
def api_list_placeholders():
    """Combined catalog used by the admin page (single fetch).

    Returns:
        {
          "builtins": [{name, category, description, sample}, ...],
          "custom":   [{id, name, value, description, is_active, ...}, ...],
        }
    """
    builtins = PlaceholderProcessor.get_builtin_placeholder_catalog()

    with session_scope() as session:
        rows = CustomPlaceholderRepository(session).list_all()
        custom = [r.to_dict() for r in rows]

    # Surface override warnings inline: if a custom row shadows a built-in
    # of the same name, mark it so the UI can show a yellow indicator.
    builtin_names = {b['name'] for b in builtins}
    for c in custom:
        c['shadows_builtin'] = c['name'] in builtin_names

    return jsonify({'builtins': builtins, 'custom': custom})


@api_bp.route('/placeholders/custom', methods=['GET'])
@api_key_or_login_required
def api_list_custom_placeholders():
    """Custom rows only — useful for clients that don't need the reference."""
    with session_scope() as session:
        rows = CustomPlaceholderRepository(session).list_all()
        return jsonify({'custom': [r.to_dict() for r in rows]})


@api_bp.route('/placeholders/custom', methods=['POST'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_create_custom_placeholder():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip().lower()
    err = _validate_name(name)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    with session_scope() as session:
        repo = CustomPlaceholderRepository(session)
        if repo.get_by_name(name):
            return jsonify({
                'success': False,
                'error': f"placeholder '{name}' already exists",
            }), 409
        row = CustomPlaceholder(
            name=name,
            value=data.get('value', '') or '',
            description=(data.get('description') or '').strip() or None,
            is_active=bool(data.get('is_active', True)),
        )
        repo.create(row)
        return jsonify({'success': True, 'placeholder': row.to_dict()}), 201


@api_bp.route('/placeholders/custom/<int:placeholder_id>', methods=['PUT'])
@api_key_or_login_required
@limiter.limit("60/minute")
def api_update_custom_placeholder(placeholder_id: int):
    data = request.get_json(silent=True) or {}

    with session_scope() as session:
        repo = CustomPlaceholderRepository(session)
        row = repo.get(placeholder_id)
        if row is None:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        # Name change requires re-validating uniqueness. Rare, but supported
        # so an operator who typo'd the name on create doesn't have to
        # delete-and-recreate (which would lose any per-name history).
        if 'name' in data:
            new_name = (data.get('name') or '').strip().lower()
            err = _validate_name(new_name)
            if err:
                return jsonify({'success': False, 'error': err}), 400
            if new_name != row.name:
                clash = repo.get_by_name(new_name)
                if clash is not None:
                    return jsonify({
                        'success': False,
                        'error': f"placeholder '{new_name}' already exists",
                    }), 409
                row.name = new_name

        if 'value' in data:
            row.value = data.get('value') or ''
        if 'description' in data:
            row.description = (data.get('description') or '').strip() or None
        if 'is_active' in data:
            row.is_active = bool(data.get('is_active'))

        return jsonify({'success': True, 'placeholder': row.to_dict()})


@api_bp.route('/placeholders/custom/<int:placeholder_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_delete_custom_placeholder(placeholder_id: int):
    with session_scope() as session:
        repo = CustomPlaceholderRepository(session)
        row = repo.get(placeholder_id)
        if row is None:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        repo.delete(row)
        return jsonify({'success': True})
