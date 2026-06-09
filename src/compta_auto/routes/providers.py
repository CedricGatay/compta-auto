"""Provider fetch routes (Spotify, OpenAI, Free, Orange, Sosh, Freebox, OVH, Engie)."""

from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import Settings
from ..providers.base import AuthError
from ..repositories import Repository
from ..services import get_credential, save_credential
from ..services.fetch_service import run_provider_fetch
from .deps import get_fernet, get_repo, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["providers"])


@router.post("/fetch-spotify")
def api_fetch_spotify(
    sp_dc: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Fetch Spotify invoices with SSE progress updates."""
    from ..spotify import fetch_spotify_invoices_stream

    effective_sp_dc = get_credential(repo, "spotify_sp_dc", sp_dc, fernet=fernet)
    if not effective_sp_dc:
        raise HTTPException(status_code=400, detail="No sp_dc cookie provided or saved.")
    save_credential(repo, "spotify_sp_dc", effective_sp_dc, fernet=fernet)

    def event_stream():
        try:
            stream = fetch_spotify_invoices_stream(effective_sp_dc, settings.raw_dir)
            yield from run_provider_fetch(stream, settings, repo, "spotify")
        except SystemExit:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Authentication failed. Your sp_dc cookie is invalid or expired.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/fetch-chatgpt")
def api_fetch_chatgpt(
    bearer_token: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Fetch ChatGPT subscription invoices with SSE progress updates."""
    from ..openai_invoices import fetch_chatgpt_invoices_stream

    effective_token = get_credential(repo, "chatgpt_bearer", bearer_token, fernet=fernet)
    if not effective_token:
        raise HTTPException(status_code=400, detail="No Bearer token provided or saved.")
    save_credential(repo, "chatgpt_bearer", effective_token, fernet=fernet)

    stream = fetch_chatgpt_invoices_stream(effective_token, settings.raw_dir)
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "openai"),
        media_type="text/event-stream",
    )


@router.post("/free-mobile-login")
def api_free_mobile_login(
    username: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    fernet: Fernet = Depends(get_fernet),
):
    """Step 1: Login to Free Mobile (triggers OTP via email)."""
    from ..free_invoices import login

    effective_user = get_credential(repo, "free_username", username, fernet=fernet)
    effective_pass = get_credential(repo, "free_password", password, fernet=fernet)
    if not effective_user or not effective_pass:
        return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

    try:
        session_cookies, csrf_token, otp_id = login(effective_user, effective_pass)
        save_credential(repo, "free_username", effective_user, fernet=fernet)
        save_credential(repo, "free_password", effective_pass, fernet=fernet)
        return {
            "status": "otp_required",
            "session_cookies": session_cookies,
            "csrf_token": csrf_token,
            "otp_id": otp_id,
        }
    except AuthError as exc:
        return JSONResponse(status_code=401, content={"error": str(exc)})
    except Exception:
        logger.exception("Free Mobile login failed")
        return JSONResponse(status_code=500, content={"error": "Login failed. Check server logs."})


@router.post("/free-mobile-otp")
def api_free_mobile_otp(
    session_cookies: str = Form(...),
    csrf_token: str = Form(...),
    otp_code: str = Form(...),
    otp_id: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Step 2: Validate OTP and download Free Mobile invoices."""
    from ..free_invoices import fetch_free_invoices_stream

    otp_id_int = int(otp_id) if otp_id else None
    stream = fetch_free_invoices_stream(
        session_cookies, csrf_token, otp_code, otp_id_int, settings.raw_dir,
    )
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "free_mobile"),
        media_type="text/event-stream",
    )


@router.post("/orange-fetch")
def api_orange_fetch(
    username: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Authenticate to Orange and download all invoices."""
    from ..orange_invoices import fetch_orange_invoices_no_otp_stream

    effective_user = get_credential(repo, "orange_username", username, fernet=fernet)
    effective_pass = get_credential(repo, "orange_password", password, fernet=fernet)
    if not effective_user or not effective_pass:
        return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

    save_credential(repo, "orange_username", effective_user, fernet=fernet)
    save_credential(repo, "orange_password", effective_pass, fernet=fernet)

    stream = fetch_orange_invoices_no_otp_stream(effective_user, effective_pass, settings.raw_dir)
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "orange"),
        media_type="text/event-stream",
    )


@router.post("/sosh-fetch")
def api_sosh_fetch(
    username: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Authenticate to Sosh and download all invoices."""
    from ..orange_invoices import fetch_orange_invoices_no_otp_stream

    effective_user = get_credential(repo, "sosh_username", username, fernet=fernet)
    effective_pass = get_credential(repo, "sosh_password", password, fernet=fernet)
    if not effective_user or not effective_pass:
        return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

    save_credential(repo, "sosh_username", effective_user, fernet=fernet)
    save_credential(repo, "sosh_password", effective_pass, fernet=fernet)

    stream = fetch_orange_invoices_no_otp_stream(
        effective_user, effective_pass, settings.raw_dir, prefix="sosh",
    )
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "sosh"),
        media_type="text/event-stream",
    )


@router.post("/freebox-fetch")
def api_freebox_fetch(
    username: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Authenticate to Freebox subscriber portal and download all invoices."""
    from ..freebox_invoices import fetch_freebox_invoices_stream

    effective_user = get_credential(repo, "freebox_username", username, fernet=fernet)
    effective_pass = get_credential(repo, "freebox_password", password, fernet=fernet)
    if not effective_user or not effective_pass:
        return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

    save_credential(repo, "freebox_username", effective_user, fernet=fernet)
    save_credential(repo, "freebox_password", effective_pass, fernet=fernet)

    stream = fetch_freebox_invoices_stream(effective_user, effective_pass, settings.raw_dir)
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "freebox"),
        media_type="text/event-stream",
    )


@router.post("/ovh-fetch")
def api_ovh_fetch(
    app_key: str = Form(""),
    app_secret: str = Form(""),
    consumer_key: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Fetch all OVH invoices via the official API."""
    from ..ovh_invoices import fetch_ovh_invoices_stream

    effective_key = get_credential(repo, "ovh_app_key", app_key, fernet=fernet)
    effective_secret = get_credential(repo, "ovh_app_secret", app_secret, fernet=fernet)
    effective_ck = get_credential(repo, "ovh_consumer_key", consumer_key, fernet=fernet)
    if not effective_key or not effective_secret or not effective_ck:
        return JSONResponse(
            status_code=400,
            content={"error": "OVH API credentials required (app key, app secret, consumer key)."},
        )

    save_credential(repo, "ovh_app_key", effective_key, fernet=fernet)
    save_credential(repo, "ovh_app_secret", effective_secret, fernet=fernet)
    save_credential(repo, "ovh_consumer_key", effective_ck, fernet=fernet)

    stream = fetch_ovh_invoices_stream(effective_key, effective_secret, effective_ck, settings.raw_dir)
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "ovh"),
        media_type="text/event-stream",
    )


@router.post("/engie-login")
def api_engie_login(
    email: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    fernet: Fernet = Depends(get_fernet),
):
    """Step 1: Login to Engie Pro (triggers MFA code via email)."""
    from ..engie_invoices import login

    effective_email = get_credential(repo, "engie_email", email, fernet=fernet)
    effective_pass = get_credential(repo, "engie_password", password, fernet=fernet)
    if not effective_email or not effective_pass:
        return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

    try:
        session_cookies, factor_id, user_id, form_build_id = login(effective_email, effective_pass)
        save_credential(repo, "engie_email", effective_email, fernet=fernet)
        save_credential(repo, "engie_password", effective_pass, fernet=fernet)
        if not factor_id:
            return {"status": "authenticated", "session_cookies": session_cookies}
        return {
            "status": "otp_required",
            "session_cookies": session_cookies,
            "factor_id": factor_id,
            "user_id": user_id,
            "form_build_id": form_build_id,
        }
    except AuthError as exc:
        return JSONResponse(status_code=401, content={"error": str(exc)})
    except Exception:
        logger.exception("Engie login failed")
        return JSONResponse(status_code=500, content={"error": "Login failed. Check server logs."})


@router.post("/engie-otp")
def api_engie_otp(
    session_cookies: str = Form(...),
    factor_id: str = Form(...),
    user_id: str = Form(...),
    form_build_id: str = Form(...),
    otp_code: str = Form(...),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Step 2: Validate OTP and download Engie Pro invoices."""
    from ..engie_invoices import fetch_engie_invoices_stream

    stream = fetch_engie_invoices_stream(
        session_cookies, factor_id, user_id, form_build_id, otp_code, settings.raw_dir,
    )
    return StreamingResponse(
        run_provider_fetch(stream, settings, repo, "engie"),
        media_type="text/event-stream",
    )


@router.post("/free-mobile-auto")
def api_free_mobile_auto(
    username: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Single-step Free Mobile fetch: login + auto-read OTP from mailbox + download."""
    from ..free_invoices import login, fetch_free_invoices_stream
    from ..otp_reader import read_free_mobile_otp, OtpReadError

    effective_user = get_credential(repo, "free_username", username, fernet=fernet)
    effective_pass = get_credential(repo, "free_password", password, fernet=fernet)
    if not effective_user or not effective_pass:
        raise HTTPException(status_code=400, detail="No credentials provided or saved.")

    def event_stream():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Logging in to Free Mobile…'})}\n\n"
            session_cookies, csrf_token, otp_id = login(effective_user, effective_pass)
            save_credential(repo, "free_username", effective_user, fernet=fernet)
            save_credential(repo, "free_password", effective_pass, fernet=fernet)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Waiting for OTP email in mailbox…'})}\n\n"
            otp_code = read_free_mobile_otp(timeout=90)

            yield f"data: {json.dumps({'type': 'status', 'message': f'OTP code retrieved, validating…'})}\n\n"
            stream = fetch_free_invoices_stream(
                session_cookies, csrf_token, otp_code, otp_id, settings.raw_dir,
            )
            yield from run_provider_fetch(stream, settings, repo, "free_mobile")
        except AuthError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        except OtpReadError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Auto-OTP failed: {exc}. Try manual flow.'})}\n\n"
        except Exception:
            logger.exception("Free Mobile auto-fetch failed")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Auto-fetch failed. Check server logs.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/engie-auto")
def api_engie_auto(
    email: str = Form(""),
    password: str = Form(""),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
    fernet: Fernet = Depends(get_fernet),
) -> StreamingResponse:
    """Single-step Engie fetch: login + auto-read OTP from mailbox + download."""
    from ..engie_invoices import login, fetch_engie_invoices_stream
    from ..otp_reader import read_engie_otp, OtpReadError

    effective_email = get_credential(repo, "engie_email", email, fernet=fernet)
    effective_pass = get_credential(repo, "engie_password", password, fernet=fernet)
    if not effective_email or not effective_pass:
        raise HTTPException(status_code=400, detail="No credentials provided or saved.")

    def event_stream():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Logging in to Engie Pro…'})}\n\n"
            session_cookies, factor_id, user_id, form_build_id = login(effective_email, effective_pass)
            save_credential(repo, "engie_email", effective_email, fernet=fernet)
            save_credential(repo, "engie_password", effective_pass, fernet=fernet)

            if not factor_id:
                # No MFA needed — device already trusted, use a dummy OTP flow
                # that skips validation (session_cookies already authenticated)
                yield f"data: {json.dumps({'type': 'status', 'message': 'No MFA required, fetching invoices…'})}\n\n"
                from ..engie_invoices import _build_opener, _restore_cookies, _fetch_invoices_page, _extract_invoice_links, _download_invoice
                opener, cj = _build_opener()
                _restore_cookies(cj, session_cookies)
                page_html = _fetch_invoices_page(opener)
                invoices = _extract_invoice_links(page_html)
                settings.raw_dir.mkdir(parents=True, exist_ok=True)
                downloaded = 0
                for inv in invoices:
                    fname = _download_invoice(opener, inv, settings.raw_dir)
                    if fname:
                        downloaded += 1
                yield f"data: {json.dumps({'type': 'done', 'result': {'total': len(invoices), 'downloaded': downloaded, 'skipped': len(invoices) - downloaded, 'errors': []}})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'status', 'message': 'Waiting for OTP email in mailbox…'})}\n\n"
            otp_code = read_engie_otp(timeout=90)

            yield f"data: {json.dumps({'type': 'status', 'message': f'OTP code retrieved, validating…'})}\n\n"
            stream = fetch_engie_invoices_stream(
                session_cookies, factor_id, user_id, form_build_id, otp_code, settings.raw_dir,
            )
            yield from run_provider_fetch(stream, settings, repo, "engie")
        except AuthError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        except OtpReadError as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': f'Auto-OTP failed: {exc}. Try manual flow.'})}\n\n"
        except Exception:
            logger.exception("Engie auto-fetch failed")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Auto-fetch failed. Check server logs.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
