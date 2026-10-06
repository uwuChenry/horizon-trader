# Implementation decisions and audit trail

- Protocol and nine candidate configurations written before development returns.
- New engine uses prior-close sizing, whole orders at nominal historical prices,
  ideal gross dividend reinvestment, and explicit funding. The legacy results are
  reproduced separately rather than compared as if they use the same accounting.
- Development selected `rotation_126` automatically. Validation then failed for
  every candidate. No strategy parameters or selection rule were changed.
- Before historical confirmation, independent review requested stricter input/
  protocol hash checks and a zero-transaction-cost diagnostic. Both added. The
  latter retains financing and whole-share sizing, is not a deployable scenario,
  and cannot select a strategy. This is one extra diagnostic beyond the original
  nine stress scenarios, not an added signal trial. Primary results are unchanged.
- The exact code hashes and timestamps at each stage are in results/*_manifest.json.
