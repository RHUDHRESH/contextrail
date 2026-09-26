"""GET /r/{run_id}: the stored receipt as a read-only, printable page behind a signed link."""

import uuid

import httpx
import pytest

from contextrail.app_state import build_platform
from contextrail.main import create_app
from contextrail.receipts import build_receipt
from contextrail.settings import Settings
from contextrail.surfaces.receipt_page import receipt_url

SECRET = "test-link-secret"  # a test value, not a credential
ANIL = "Give Anil the same access as Rahul Mehta"


@pytest.fixture
async def page(rail):
    runner, _ = rail
    settings = Settings(_env_file=None, decision_link_secret=SECRET, public_url="https://cr.example.test")
    platform = build_platform(settings, runner=runner)
    app = create_app(settings, platform=platform)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.example.test") as c:
        yield c, platform, settings


async def _receipt(platform, text=ANIL):
    view = await platform.door.start_run(text, channel="slack", actor_external_id="U0ANIL001")
    return await build_receipt(platform.db, view.run_id, people=platform.door.people, modes=platform.modes)


async def test_the_signed_link_shows_the_stored_receipt(page):
    client, platform, settings = page
    receipt = await _receipt(platform)
    url = receipt_url(settings, receipt.run_id)
    assert url.startswith(f"https://cr.example.test/r/{receipt.run_id}?sig=")
    r = await client.get(url)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "POL-ACC-003" in html and "Dana Osei" in html and "Meera Iyer" in html and "FIXTURE" in html
    assert receipt.digest in html and receipt.body["capsule"]["digest"] in html and "chain intact" in html
    assert "<s>AWS payments-prod AdministratorAccess</s>" in html      # refusals stay visible, struck through
    assert "@media print" in html
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]


@pytest.mark.parametrize("sig", [None, "", "0" * 64, "not-hex-at-all"])
async def test_a_missing_or_wrong_signature_is_refused(page, sig):
    client, platform, _ = page
    receipt = await _receipt(platform)
    params = {} if sig is None else {"sig": sig}
    assert (await client.get(f"/r/{receipt.run_id}", params=params)).status_code == 403


async def test_a_signature_for_another_run_does_not_open_this_one(page):
    client, platform, settings = page
    receipt = await _receipt(platform)
    other = receipt_url(settings, uuid.uuid4()).split("?sig=")[1]
    assert (await client.get(f"/r/{receipt.run_id}", params={"sig": other})).status_code == 403


async def test_a_run_without_a_receipt_yet_is_404(page):
    client, platform, settings = page
    view = await platform.door.start_run(ANIL, channel="slack", actor_external_id="U0ANIL001")
    assert (await client.get(receipt_url(settings, view.run_id))).status_code == 404


async def test_untrusted_request_text_is_escaped(page):
    client, platform, settings = page
    receipt = await _receipt(platform, ANIL + ' <script>alert("x")</script>')
    html = (await client.get(receipt_url(settings, receipt.run_id))).text
    assert "<script>" not in html and "&lt;script&gt;" in html


async def test_an_unset_or_placeholder_link_secret_closes_the_page(rail):
    runner, _ = rail
    settings = Settings(_env_file=None, decision_link_secret="change-me")
    app = create_app(settings, platform=build_platform(settings, runner=runner))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        r = await client.get(f"/r/{uuid.uuid4()}", params={"sig": "0" * 64})
    assert r.status_code == 503
