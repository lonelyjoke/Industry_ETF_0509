from src.universe import load_universe
from src.utils import load_config


def test_config_loads_and_has_universe():
    cfg = load_config("config.yaml")
    universe = load_universe(cfg)
    assert len(universe) >= 16
    assert {"etf_code", "etf_name", "theme"}.issubset(universe.columns)
    assert cfg["backtest"]["top_k"] in (1, 2)
