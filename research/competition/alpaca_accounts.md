# Alpaca paper accounts: research, AI competition, human competition

Updated 2026-10-08. The owner confirms an Alpaca paper account already exists and
reconfirms the aggressive AI competition objective: maximize the chance of
finishing first, accepting a possible simulated wipeout.

This is a setup specification. No additional accounts were created, API keys
read, accounts reset, orders submitted, or unattended runner deployed.

## Verified platform support

Alpaca currently documents up to three paper accounts under one login, with
separate balances and positions. Select the account dropdown in the dashboard,
choose **Open New Paper Account**, and generate credentials for each new account.
[Three-account limit](https://alpaca.markets/learn/start-paper-trading),
[creation instructions](https://docs.alpaca.markets/us/docs/paper-trading).

Alpaca staff also describe additional owner logins as a supported way to obtain
more paper accounts; this is not an unlimited-account feature of one login.
[Staff clarification](https://forum.alpaca.markets/t/feature-request-more-paper-trading-accounts/18125/2).

## Proposed allocation

| Local profile | Account | Role |
|---|---|---|
| research | Existing paper account | Forward testing and order-integration experiments; preserve existing history |
| competition_ai | New account, USD 5,000 | AI decisions and logged paper execution |
| competition_human | New account, USD 5,000 | Owner's manual competition trades; automated reporting only |

These are local profile names, not a claim that Alpaca supports arbitrary account
display names. Store the actual account identifiers after read-only verification.
Each new account must have its own key/secret pair. Store credentials locally in
the git-ignored environment or a secret store, never in this file or chat.

## Forward-test isolation

Multiple strategies in one broker account share buying power and net positions.
Order labels and virtual ledgers can attribute trades, but do not give independent
broker margin, fill paths, or protection from another strategy closing a position.

Initially, reserve the research broker account for a selected executable strategy
or an explicitly combined portfolio. Additional independent strategies can run
in separately labeled shadow ledgers, whose fills are modeled. For simultaneous
independent broker forward tests, obtain additional paper accounts through the
supported owner-login arrangement. Report modeled and broker-simulated results
separately.

Market-data subscription limits are owner-level, while trading-API limits are
account-level. Share a data collector within the owner's setup rather than
assuming each key provides a separate data allowance.
[Alpaca staff explanation](https://forum.alpaca.markets/t/what-constitutes-an-api-call/16502/3).

## AI versus human experiment

- Begin both comparison accounts with USD 5,000 and the same recorded start time,
  eligible products, buying-power constraints, and fee treatment. Preserve all
  subsequent cash movements and prevent competition resets from erasing losses.
- The club's original start was October 7. Record actual account creation and
  first-trade times; do not fabricate fills for elapsed competition sessions.
- Score realized gains minus realized losses and the agreed costs. Also report
  total equity, unrealized P&L, drawdown, leverage, exposure, and trade count.
- Close all positions by December 31, 2026, as required by the confirmed mandate.
- Record AI information timestamps, thesis, instrument choice, size, planned
  exits, decisions to hold, orders, fills, and any manual intervention. For a
  meaningful comparison, record whether the human account used AI suggestions.
- Retain SOXX and QQQ as separately labeled benchmark portfolios; they need not
  consume broker paper-account slots.
- A switch to Alpaca does not automatically replicate the original IBKR margin,
  product, or fee rules. Keep competition scoring and any IBKR-equivalent cost
  ledger separate. Never infer futures support merely from contest eligibility.

## Integration still required

The repo currently has IBKR paper execution and internal ledgers, but no Alpaca
adapter. Implement account-specific state and reporting, then verify the three
account identities and balances without submitting orders. The order path should
be restricted to the research and AI paper profiles; the human profile is for
reporting. This is an application restriction, not a claim that Alpaca issues a
special read-only key.

Automated decisions require a persistent scheduled runner, data access, and a
configured model runtime. A conversation alone is not an unattended trading
process. Log model/runtime versions and keep all runtime/API spending separate
from simulated account capital.

The existing [competition plan](README.md) remains a proposed strategy, not a proven
optimal portfolio. Review [execution realism](../execution_realism/README.md)
before treating broker paper fills as evidence of live IBKR performance.
