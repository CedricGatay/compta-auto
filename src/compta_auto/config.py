from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMPTA_", env_file=".env", extra="ignore")

    db_path: Path = Field(default=Path("data/compta.sqlite3"))
    raw_dir: Path = Field(default=Path("data/raw"))
    renamed_dir: Path = Field(default=Path("data/renamed"))
    output_dir: Path = Field(default=Path("data/output"))
    scan_folder: str | None = None
    accounting_domain: str = ""
    min_rename_confidence: float = 0.82
    llm_extractor_command: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    use_apple_llm: bool = True
    inqom_email: str | None = None
    inqom_password: str | None = None
    inqom_client_id: str = ""
    inqom_fiscal_year_start_month: int = 8
    sale_vendor_markers: str = ""  # comma-separated list of vendor keywords indicating sale invoices

    @property
    def accounting_recipient_suffix(self) -> str:
        return f"@{self.accounting_domain.lower().lstrip('@')}"

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.renamed_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
