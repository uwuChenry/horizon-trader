import pytest

from horizon_trader.execution.alpaca_check import paper_keys


def test_paper_keys_accepts_paper_key():
    assert paper_keys({"ALPACA_API_KEY": " PKabc ", "ALPACA_SECRET_KEY": "s"}) == ("PKabc", "s")


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"ALPACA_API_KEY": "PKabc"},
        {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": "s"},
        {"ALPACA_API_KEY": "AKlive", "ALPACA_SECRET_KEY": "s"},  # live key
    ],
)
def test_paper_keys_refuses_missing_or_live(env):
    with pytest.raises(SystemExit):
        paper_keys(env)
