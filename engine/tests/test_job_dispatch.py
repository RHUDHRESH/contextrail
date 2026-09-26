"""Approval jobs must have a real worker handler and must not silently lose every delivery path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contextrail.jobs import PermanentJobError, load_handlers
from contextrail.settings import Settings
from contextrail.surfaces import job_dispatch
from contextrail.surfaces.email import EmailDispatchResult

PAYLOAD = {"run_id": "c51799f8-7079-4c0d-943a-2c9f224d185e", "action_id": "A1", "approver": "p-dana",
           "params_hash": "a" * 64}


def _platform(*, slack=True, secret=True):
    settings = Settings(_env_file=None, decision_link_secret="x" * 32 if secret else "")
    return SimpleNamespace(settings=settings, door=object(), slack=object() if slack else None)


def test_every_enqueued_approval_kind_has_a_worker_handler():
    assert {"approval.dispatch", "fs.approval.mirror", "door.update"} <= set(load_handlers())


async def test_dispatch_preserves_freshservice_and_slack_delivery_when_email_is_not_preferred(monkeypatch):
    fs = AsyncMock(return_value={"status": "requested"})
    slack = AsyncMock(return_value={"status": "delivered"})
    email = AsyncMock(return_value=EmailDispatchResult(outcome="skipped", reason="prefers slack"))
    monkeypatch.setattr(job_dispatch, "handle_fs_approval_request", fs)
    monkeypatch.setattr(job_dispatch, "handle_approval_dispatch", slack)
    monkeypatch.setattr(job_dispatch, "handle_approval_dispatch_email", email)
    platform = _platform()

    await job_dispatch.approval_dispatch(platform, PAYLOAD)

    fs.assert_awaited_once_with(PAYLOAD, platform)
    slack.assert_awaited_once_with(PAYLOAD, platform.slack)
    email.assert_awaited_once()


async def test_dispatch_goes_dead_when_no_channel_can_reach_the_approver(monkeypatch):
    monkeypatch.setattr(job_dispatch, "handle_fs_approval_request", AsyncMock(return_value={"status": "skipped"}))
    monkeypatch.setattr(job_dispatch, "handle_approval_dispatch", AsyncMock())
    monkeypatch.setattr(job_dispatch, "handle_approval_dispatch_email", AsyncMock())

    with pytest.raises(PermanentJobError, match="no approval could be delivered"):
        await job_dispatch.approval_dispatch(_platform(slack=False, secret=False), PAYLOAD)


async def test_mirror_and_door_update_forward_to_their_idempotent_delivery_functions(monkeypatch):
    mirror = AsyncMock(return_value={"status": "mirrored"})
    update = AsyncMock(return_value={"status": "updated"})
    monkeypatch.setattr(job_dispatch, "handle_fs_approval_mirror", mirror)
    monkeypatch.setattr(job_dispatch, "handle_door_update", update)
    platform = _platform()

    await job_dispatch.approval_mirror(platform, PAYLOAD)
    await job_dispatch.door_update(platform, PAYLOAD)

    mirror.assert_awaited_once_with(PAYLOAD, platform)
    update.assert_awaited_once_with(PAYLOAD, platform.slack)
