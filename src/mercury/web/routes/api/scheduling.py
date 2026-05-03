"""Scheduled job API routes."""

import uuid
from datetime import datetime

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
)
# SchedulerService is import-deferred (the scheduler module is heavy and only
# needed when these routes actually fire).
from ....services.scheduler_service import SchedulerService


@api_bp.route('/scheduling/jobs', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_scheduled_jobs():
    """List all scheduled jobs."""
    service = SchedulerService(use_async=False)
    jobs = service.get_all_jobs()

    return jsonify({'jobs': [j.to_dict() for j in jobs]})


@api_bp.route('/scheduling/jobs', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_create_scheduled_job():
    """Create a new scheduled job."""
    data = request.get_json(silent=True) or {}

    if not data.get('name'):
        return jsonify({'error': 'Job name is required'}), 400
    if not data.get('campaign_id'):
        return jsonify({'error': 'Campaign ID is required'}), 400

    service = SchedulerService(use_async=False)
    job_id = data.get('job_id', str(uuid.uuid4()))
    schedule_type = data.get('schedule_type', 'once')

    try:
        if schedule_type == 'once':
            run_at = datetime.fromisoformat(data['run_at'])
            job = service.schedule_once(
                job_id=job_id,
                name=data['name'],
                run_at=run_at,
                callback=lambda: None,  # Placeholder - actual execution handled by campaign
                campaign_id=data['campaign_id'],
            )
        elif schedule_type == 'recurring':
            if not data.get('cron_expression'):
                return jsonify({'error': 'Cron expression required for recurring jobs'}), 400
            job = service.schedule_recurring(
                job_id=job_id,
                name=data['name'],
                cron_expression=data['cron_expression'],
                callback=lambda: None,
                campaign_id=data['campaign_id'],
                timezone=data.get('timezone') or None,
                max_runs=int(data['max_runs']) if data.get('max_runs') else None,
            )
        elif schedule_type == 'interval':
            if not data.get('interval_seconds'):
                return jsonify({'error': 'Interval seconds required'}), 400
            job = service.schedule_interval(
                job_id=job_id,
                name=data['name'],
                interval_seconds=int(data['interval_seconds']),
                callback=lambda: None,
                campaign_id=data['campaign_id'],
                timezone=data.get('timezone') or None,
                max_runs=int(data['max_runs']) if data.get('max_runs') else None,
            )
        else:
            return jsonify({'error': f'Invalid schedule type: {schedule_type}'}), 400

        return jsonify({'success': True, 'job': job.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/scheduling/jobs/<job_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_cancel_scheduled_job(job_id):
    """Cancel a scheduled job."""
    service = SchedulerService(use_async=False)
    success = service.cancel_job(job_id)
    return jsonify({'success': success})


@api_bp.route('/scheduling/jobs/<job_id>/pause', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_pause_scheduled_job(job_id):
    """Pause a scheduled job."""
    service = SchedulerService(use_async=False)
    service.pause_job(job_id)
    return jsonify({'success': True})


@api_bp.route('/scheduling/jobs/<job_id>/resume', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_resume_scheduled_job(job_id):
    """Resume a paused job."""
    service = SchedulerService(use_async=False)
    service.resume_job(job_id)
    return jsonify({'success': True})
