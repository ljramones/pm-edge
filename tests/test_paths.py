from pathlib import Path

from core.config import Settings
from utils.paths import REPO_ROOT, resolve_repo_path


def test_resolve_repo_path_uses_repo_root_for_relative_paths() -> None:
    assert resolve_repo_path(Path("data/processed/example.parquet")) == (
        REPO_ROOT / "data/processed/example.parquet"
    )


def test_settings_resolve_data_paths_from_repo_root() -> None:
    settings = Settings(
        data_dir=Path("data"),
        raw_data_dir=Path("data/raw"),
        processed_data_dir=Path("data/processed"),
        llm_cache_dir=Path("data/processed/llm_cache"),
        paper_trader_state_path=Path("data/processed/live_paper/state.json"),
        paper_trader_audit_log_path=Path("data/processed/live_paper/audit.jsonl"),
        paper_trader_review_flag_path=Path("data/processed/live_paper/review_approval.txt"),
    )

    assert settings.data_dir == REPO_ROOT / "data"
    assert settings.processed_data_dir == REPO_ROOT / "data/processed"
    assert settings.llm_cache_dir == REPO_ROOT / "data/processed/llm_cache"
