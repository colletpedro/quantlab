"""B6 — universo default de tickers (RF-CLI-01, CA-01.1)."""

from pathlib import Path

import pytest
import yaml

from quantlab.exceptions import ConfigError
from quantlab.universe import load_default_universe


def _write_yaml(path: Path, content: object) -> Path:
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return path


@pytest.mark.unit
def test_loads_tickers_in_file_order(tmp_path: Path) -> None:
    file_path = _write_yaml(
        tmp_path / "universe.yml",
        {
            "universe": [
                {"ticker": "AAPL", "sector": "Information Technology"},
                {"ticker": "MSFT", "sector": "Information Technology"},
                {"ticker": "XOM", "sector": "Energy"},
            ]
        },
    )

    assert load_default_universe(file_path) == ["AAPL", "MSFT", "XOM"]


@pytest.mark.unit
def test_uppercases_tickers(tmp_path: Path) -> None:
    file_path = _write_yaml(tmp_path / "universe.yml", {"universe": [{"ticker": "aapl"}]})
    assert load_default_universe(file_path) == ["AAPL"]


@pytest.mark.unit
def test_missing_file_raises_actionable_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "nao-existe.yml"
    with pytest.raises(ConfigError, match="--tickers"):
        load_default_universe(missing)


@pytest.mark.unit
def test_missing_universe_key_raises(tmp_path: Path) -> None:
    file_path = _write_yaml(tmp_path / "universe.yml", {"version": 1})
    with pytest.raises(ConfigError, match="universe"):
        load_default_universe(file_path)


@pytest.mark.unit
def test_entry_without_ticker_raises(tmp_path: Path) -> None:
    file_path = _write_yaml(tmp_path / "universe.yml", {"universe": [{"sector": "Energy"}]})
    with pytest.raises(ConfigError, match="ticker"):
        load_default_universe(file_path)


@pytest.mark.unit
def test_empty_universe_raises(tmp_path: Path) -> None:
    file_path = _write_yaml(tmp_path / "universe.yml", {"universe": []})
    with pytest.raises(ConfigError, match="vazia"):
        load_default_universe(file_path)


@pytest.mark.unit
def test_the_real_project_universe_file_loads_successfully() -> None:
    """O arquivo real do projeto, não um fixture — prova que os dois concordam."""
    real_path = Path(__file__).resolve().parents[2] / "config" / "universe.yml"
    tickers = load_default_universe(real_path)

    assert len(tickers) == 20
    assert "AAPL" in tickers
    assert tickers == [ticker.upper() for ticker in tickers]
