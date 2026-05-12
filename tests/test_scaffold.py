from pathlib import Path


def test_expected_project_directories_exist() -> None:
    root = Path(__file__).resolve().parents[1]

    for relative_path in [
        "src/core",
        "src/data",
        "src/features",
        "src/models",
        "src/strategies",
        "src/execution",
        "src/backtesting",
        "src/utils",
        "notebooks",
        "config",
        "data/raw",
        "data/processed",
        "tests",
        "scripts",
    ]:
        assert (root / relative_path).is_dir()
