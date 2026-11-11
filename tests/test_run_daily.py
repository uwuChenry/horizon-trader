from horizon_trader.config import DEFAULT_CONFIG, load_settings
from horizon_trader.sleeves import build_sleeve

# End-to-end runs (dry-run, shadow, what-if, paper) are in test_live.py.


def test_default_config_builds_every_sleeve():
    settings = load_settings(DEFAULT_CONFIG)
    assert sum(s.allocation for s in settings.sleeves.values()) <= 1.0
    for name, cfg in settings.sleeves.items():
        build_sleeve(name, cfg)
