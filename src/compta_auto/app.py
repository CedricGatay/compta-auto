"""Compta Auto — FastAPI application factory.

This module wires up the application: creates the FastAPI instance,
configures dependency injection, mounts static files, and includes routers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from .config import Settings, get_settings
from .db import Database
from .repositories import Repository
from .routes import credentials, documents, inqom, mails, providers, rules, scan
from .routes.deps import get_db as get_db_dep_key, get_fernet as get_fernet_dep_key, get_repo as get_repo_dep_key, get_settings as get_settings_dep_key
from .services.crypto import get_fernet as make_fernet

templates = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    db = Database(app_settings.db_path)
    db.init()
    fernet = make_fernet(app_settings.db_path)

    app = FastAPI(title="Compta Auto")
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- Dependency overrides ---
    # Make Settings, Database, and Repository available via Depends()

    def get_repo() -> Repository:
        conn = db.connect()
        try:
            yield Repository(conn)
            conn.commit()
        finally:
            conn.close()

    def get_settings_dep() -> Settings:
        return app_settings

    def get_db_dep() -> Database:
        return db

    def get_fernet_dep():
        return fernet

    app.dependency_overrides[get_repo_dep_key] = get_repo
    app.dependency_overrides[get_settings_dep_key] = get_settings_dep
    app.dependency_overrides[get_db_dep_key] = get_db_dep
    app.dependency_overrides[get_fernet_dep_key] = get_fernet_dep

    # --- Index route (needs templates + multiple repo queries) ---

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, repo: Repository = Depends(get_repo)) -> HTMLResponse:
        last_scan_folder = repo.get_app_state("last_scan_folder") or app_settings.scan_folder or ""
        last_scan_folder_date = repo.get_app_state("last_scan_folder_date") or ""
        last_fetch = {
            provider: repo.get_app_state(f"last_fetch_{provider}") or ""
            for provider in (
                "spotify", "openai", "free_mobile", "orange", "sosh", "freebox", "ovh", "engie",
            )
        }
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "runs": repo.list_runs(),
                "mails": repo.list_mails(),
                "documents": repo.list_documents(),
                "provider_tasks": repo.list_provider_tasks(),
                "rules": repo.list_rules(),
                "settings": app_settings,
                "last_scan_folder": last_scan_folder,
                "last_scan_folder_date": last_scan_folder_date,
                "last_fetch": last_fetch,
                "provider_hint_counts": repo.count_provider_hints(),
                "missing_providers": repo.list_missing_providers(),
            },
        )

    # --- Admin routes ---

    @app.post("/reset")
    def reset(repo: Repository = Depends(get_repo)):
        """Reset all data except rules, delete renamed files, and allow reprocessing."""
        import shutil

        repo.reset_all()
        if app_settings.renamed_dir.exists():
            shutil.rmtree(app_settings.renamed_dir)
            app_settings.renamed_dir.mkdir(parents=True, exist_ok=True)
        if app_settings.raw_dir.exists():
            shutil.rmtree(app_settings.raw_dir)
            app_settings.raw_dir.mkdir(parents=True, exist_ok=True)
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/", status_code=303)

    @app.post("/purge")
    def purge(repo: Repository = Depends(get_repo)):
        """Purge ALL data (rules, documents, mails, etc.) except stored credentials."""
        import shutil

        repo.purge_all()
        if app_settings.renamed_dir.exists():
            shutil.rmtree(app_settings.renamed_dir)
            app_settings.renamed_dir.mkdir(parents=True, exist_ok=True)
        if app_settings.raw_dir.exists():
            shutil.rmtree(app_settings.raw_dir)
            app_settings.raw_dir.mkdir(parents=True, exist_ok=True)
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/", status_code=303)

    @app.post("/purge-mails")
    def purge_mails(repo: Repository = Depends(get_repo)):
        """Purge only mail scan data (mails, attachments, provider tasks). Documents and rules are kept."""
        repo.purge_mails()
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/", status_code=303)

    # --- Include routers ---
    app.include_router(scan.router)
    app.include_router(credentials.router)
    app.include_router(providers.router)
    app.include_router(documents.router)
    app.include_router(inqom.router)
    app.include_router(mails.router)
    app.include_router(rules.router)

    return app


app = create_app()
