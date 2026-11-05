# LLMs in trading strategies: what the evidence supports

*Survey written 2026-09-25 for horizon-trader. I read full texts where they were reachable (arXiv HTML, author slides). SSRN pages returned 403, so a few papers are summarised from abstracts only, and those are marked.*

## Bottom line

The only LLM trading result that holds up after the model's training cutoff is short-horizon news reaction. LLM-read headlines and news embeddings predict the next day's return, and this survives on post-cutoff data and on point-in-time models. The edge sits in small caps, costs about 20 bps a round trip to trade, and has been decaying quickly: Lopez-Lira & Tang's Sharpe fell from 6.5 in late 2021 to 1.2 in 2024. At horizons this account can afford (weeks to months, large caps), published effects are much weaker: value-weighted Sharpe around 0.4-0.6 gross, or only six independent months of data. These are also the settings where memorization bias is worst, because models know the most about large, well-covered firms. Autonomous LLM trading agents fail independent tests: over 20 years on point-in-time S&P 500 names with costs, they lose to buy-and-hold. LLM "alpha miners" report good numbers, but on Chinese A-shares and with search loops that are never corrected for multiple testing. Time-series foundation models don't beat simple baselines on returns. In industry, LLMs are used as research accelerators, with every output passing the same validation as human research, not as traders. For horizon-trader, the house rule (LLM signals are forward-test only) is correct and well supported by the literature. The realistic job for an LLM here is a slow, low-turnover signal that is logged and forward-tested, plus research hygiene. Expect years of forward data before you can tell anything, and a likely result of "no edge".

---

## 1. LLMs as text-to-signal

| Paper | What / data | Headline | Costs | Post-cutoff evidence | My read |
|---|---|---|---|---|---|
| Lopez-Lira & Tang, *Can ChatGPT forecast stock price movements?* (v6, Oct 2025) | GPT-4 scores RavenPack headlines; 4,123 firms, **Oct 2021-May 2024** (all after GPT-4's cutoff) | ~90% hit rate on the **non-tradable** opening reaction. The tradable next-day drift has Sharpe 2.97 (overnight news) | Cumulative >300% at 5 bps round trip, >100% at 10 bps, **unprofitable at 20 bps** | Yes, the whole sample. Sharpe by year: **6.54 (Q4 2021), 3.68, 2.33, 1.22 (2024)** | Credible, and a textbook case of alpha decay. Stronger in small stocks (small-firm interaction t = 4.75). Not tradable at $2 per round trip |
| Chen, Kelly & Xiu, *Expected Returns and LLMs* (2023; Kelly is AQR's head of ML) | Embeddings (BERT through GPT/LLaMA) of Refinitiv news, ridge or neural net → next-day return; 16 markets, 13 languages | Daily long-short: equal-weight Sharpe **4.62**, value-weight **1.41**. Word2vec gets 3.06 EW / 0.92 VW. **Monthly** predictions: EW 0.56-1.00, **VW 0.36-0.57** | Abstract claims "economically meaningful after costs". I couldn't see that table | Abstract says results are "not driven by look-ahead bias" | Serious work. Note that the LLM's advantage over Word2vec is mostly in equal-weight (small-cap) portfolios. At the monthly/value-weight horizon relevant to you, it is a Sharpe 0.4-0.6 long-short, before costs |
| He, Lv, Manela & Wu, *ChronoBERT/ChronoGPT* (2025) | Point-in-time models (26 annual vintages, 1999-2024, on HuggingFace `manelalab`). Dow Jones newswire 2008-2023 | Next-day EW long-short Sharpe **4.80-4.92**, versus Llama 3.1 at 4.90 | Not modeled | By construction | Lookahead is **modest for short-horizon news reaction**. The best evidence that the daily news effect is real |
| Glasserman & Lin (2023) | GPT-3.5 headline sentiment, 2015-2022; S&P 500 names plus a broader scraped set | Anonymizing firm names *raised* in-sample returns (10.7 → 13.8 bp/day on Reuters S&P 500 names). A "distraction effect", strongest for large firms | Not modeled | Out-of-sample (after Sep 2021): 6.1 bp/day original vs 12.2 anonymized | The model's knowledge of big names biases it. Anonymize large-cap text |
| Lehner & Lopez-Lira, *ChatGPT as a Time Capsule* (Apr 2026) | 12 frozen ChatGPT snapshots. Each scores ~7,000 US stocks on fundamentals only (no prices), at its own knowledge cutoff | Score predicts **1-month** returns, t = 6.0 after factor controls; **stronger for high-analyst-coverage firms**; large-cap tercile t = 2.4 | None; gross 2.55%/month long-short | Clean timing (returns after the cutoff), but only **6 independent months** | The most relevant design for you: monthly horizon, large caps, no price leakage. Far too few months to be conclusive |
| Kim, Muhn & Nikolaev (2024) | GPT-4 reads anonymized financial statements and predicts the direction of earnings changes | Beats analysts; trading Sharpe is higher than other models | Not the focus | Mostly pre-cutoff | Doubtful. Masking doesn't stop models reconstructing firms and dates (see §2), and Levy (below) finds LLMs reason poorly with numbers |
| Wu, Akin, **Martineau** et al. (2025); Yu et al., *Fast Numbers, Slow Language* (2026) | 138k earnings press releases 2005-2023; S&P 1500 call transcripts 2022-2025 | Press-release content is **fully priced at the next open**. Call-transcript tone peaks the **next trading day** | Not modeled | n/a | Together with Martineau (CFR 2022: **PEAD has been zero in large caps since 2006**), multi-week earnings-drift trades on large caps have little support |

**Pattern:** the signal is strongest at 1 day, in small caps, and equal-weighted, and it decays as LLM adoption spreads. Each step toward your setting (large caps, value-weighted, monthly, net of $1-2 per order) cuts it by a large factor.

## 2. Lookahead and memorization bias

**The evidence that it is real and large:**
- **Lopez-Lira, Tang & Zhu, *The Memorization Problem*** (2025). Before the cutoff, LLMs recall economic and financial values with "recall-level accuracy". Telling the model to ignore later information does not help, and masking fails because models reconstruct the entities and dates. After the cutoff there is no recall. Memorization also shows up in embeddings, so switching to embeddings does not escape it.
- **Sarkar & Vafa** (ICML 2025). Direct tests on earnings-call risk factors and on election outcomes find strong lookahead, and prompting does not remove it.
- **Levy, *Caution Ahead*** (J. Accounting Research 2026). Commercial LLMs show significant lookahead bias, which "may explain a large portion" of their measured predictability, and their numerical reasoning is poor.
- **Gao, Jiang & Yan** (2025). A "Lookahead Propensity" probe asks the model to recall firm-date facts from the date alone. In-sample, LLM forecasts are more accurate exactly where the probe says the model remembers. After the cutoff, both effects disappear.
- ***Profit Mirage*** (Li et al. 2025). GPT-4o, Claude 3.7 Sonnet and Grok-3 answer more than 85% of memorization probes correctly (prices, trends, event impacts). Agent backtests "evaporate once the knowledge window ends".

**Ways to get a clean backtest, from strongest to weakest:**
1. **Forward test** or **post-cutoff data only**. This is unambiguous, but the samples are short. Lopez-Lira & Tang is the model to copy.
2. **Point-in-time models.** ChronoBERT/ChronoGPT (annual vintages 1999-2024) and DatedGPT (twelve 1.3B models with annual cutoffs 2013-2024) are available. DatedGPT measures a lookahead premium of 26.4 bp per standard deviation of the signal when the model has seen the outcome period. These models are small, so they are good for embeddings and not for reasoning prompts.
3. **Model snapshots as time capsules** (Lehner & Lopez-Lira). This gives very few independent dates.
4. **Anonymization** (Glasserman & Lin). It helps with distraction but cannot remove memorization of numbers.
5. **Inference-time unlearning** (Merchant & Levy 2025). Promising, but new and unreplicated.

Glasserman & Lin and ChronoGPT show that bias is small for next-day news *reactions*. Every other study shows it is large for firm-level "what happens next" questions about well-known companies over longer horizons, which is exactly horizon-trader's large-cap swing/position use case.

## 3. LLMs as alpha/factor miners

| Paper | Setup | Result | Credibility |
|---|---|---|---|
| **AlphaAgent** (Tang et al., KDD 2025) | GPT-3.5 proposes formulas, with AST-based originality and complexity penalties. CSI 500 and S&P 500; train 2015-19, validation 2020, test 2021-24 (mostly after GPT-3.5's cutoff) | S&P 500: **IC 0.0056**, 8.7% excess return, IR 1.05. Costs: 5 bps on sells only | An IC that small doesn't fit a 1.05 IR without heavy concentration or a benchmark artifact. I found no statement of point-in-time index membership. The originality and complexity constraints are the part worth borrowing |
| **R&D-Agent(Q)** (Microsoft, 2025) | GPT-4o/o3-mini agent loop generating factors and models on Qlib | CSI 300 test **2017-2020** (before the models' cutoff): IC 0.053, 14.2% annualized vs 5.7% for Alpha158. NASDAQ-100 2024-25: IC 0.016, IR 1.77 | The main test lies inside the LLM's training window. The authors argue the model only sees schema, but the loop still picks candidates by repeated validation scores. The number of trials is not reported |

**Verdict:** these frameworks industrialize the search. The binding constraint is then how many trials were run, which none of these papers report. Man Group names p-hacking as the main risk of its own AlphaGPT (§6). Your pipeline's pre-registered direction plus a 2024+ holdout is already stricter than this literature. The "nothing clears t > 2" result is the expected outcome, not a failure of the tooling.

## 4. LLM trading agents

- **Original papers** (FinMem, FinAgent, TradingAgents, StockAgent) use 3-15 months on 3-8 hand-picked stocks. TradingAgents reports AAPL Sharpe **8.21** over Jan-Mar 2024, and neither its abstract nor its experiment section mentions costs. A three-month Sharpe of 8 is noise, not evidence.
- **FINSABER** (Li, Kim, Cucuringu & Ma; KDD 2026 oral) is the key independent test: 2004-2024, point-in-time S&P 500 membership including delisted names, and **$0.0049/share with a $0.99 minimum**, nearly IBKR Fixed. FinMem and FinAgent scored Sharpe **−0.29 to 0.24**, against **0.32-0.70** for buy-and-hold (p < 0.001), and ARIMA beat them. This happened *despite* likely memorization in their favour.
- **StockBench** (Mar-Jun 2025, 20 Dow stocks, after the cutoff): most models fail to beat buy-and-hold. **Agent Market Arena** (live): the agent framework matters more than which LLM runs it.
- **Nof1 Alpha Arena S1** (17 days of live crypto trading, Oct-Nov 2025, $10k each): four of six models lost money. It's an anecdote, but a telling one.

**Verdict:** don't build an agent that decides trades.

## 5. Time-series foundation models

- **Rahimikia, Ni & Wang, *Re(Visiting) TSFMs in Finance*** (2025): daily excess returns, 94 countries, 1990-2023. Zero-shot Chronos-large gets out-of-sample R² **−1.37%** and TimesFM-500M **−2.80%**, against CatBoost at −0.03%. Fine-tuning helps little. Pretraining from scratch on financial data helps, but the models still trail tree ensembles. Its portfolio Sharpes are gross, daily and include microcaps.
- **Noguer i Alonso & Franklin** (2026): on five US megacaps, the TSFMs "win" model rankings, but a Diebold-Mariano test finds them better than a **random walk** in only 2 model-stock pairs.
- **Kronos** (Shi et al., 2025): 12B candlestick records from 45 exchanges, pretraining through Jun 2024 and testing after. The authors report RankIC 93% above the best TSFM and an A-share backtest at 15 bps costs. There is no independent replication, and the backtest isn't US. Its volatility forecasting (9% lower MAE) is the more plausible use.

**Verdict:** there's no evidence they forecast US large-cap returns net of costs. Skip them.

## 6. Industry practice

- **BloombergGPT** (50B, finance-pretrained, 2023) was beaten by general-purpose GPT-4 on most financial NLP tasks (Li et al. 2023). Domain pretraining did not pay off.
- **Man Group, AlphaGPT** (Bloomberg, Jul 2025; Man Insights, Aug 2026). An idea generator, a code implementer and an evaluator produce signals, and "several dozen" have been approved for live trading after passing *the same thresholds as human research*. Man says explicitly that testing many variations raises the chance of "statistical artefacts". Humans stay in the loop, and no performance figures are disclosed.
- **AQR**: machine learning now drives about a fifth of the signals in its flagship multi-strategy fund (Bloomberg, Apr 2025). That's mostly conventional ML. Its LLM thinking shows up in Kelly's embeddings work (§1).
- **Pattern:** in industry, LLMs speed up research and turn text into features for ordinary models, which are validated as usual and traded at scale with low costs. No credible firm reports an LLM making trade decisions.

---

## What's worth trying in horizon-trader (ranked)

The cost frame: the reserved LLM sleeve is 10% of $5k, or $500. At IBKR Fixed, a $500 position pays $1 minimum per order, which is **20 bps a side and 40 bps a round trip**. At Tiered, the $0.35 minimum makes it about 7 bps a side plus fees. Anything daily is dead: Lopez-Lira & Tang's strategy is already unprofitable at 20 bps. Only monthly or event-gated signals with 1-3 trades a month can survive.

**1. A monthly "time-capsule" outlook score, forward-only, as the LLM sleeve.** Once a month, Claude scores each of the ~100 large caps on fundamentals from its latest 10-K/10-Q/8-K text (free from EDGAR, with acceptance timestamps). Give it no prices and no valuation multiples, following Lehner & Lopez-Lira. Use structured JSON, temperature 0 and a pinned model ID. Log the prompt hash, model ID and timestamp. The sleeve reads **only logged scores**, so the backtest path and the live path are the same code. Hold the top 3 equal-weight inside the existing rebalance band, and judge it against the universe's equal-weight row. Run it as a paper/shadow sleeve for at least 12 months before committing money. Pre-register the success rule (for example, a mean monthly rank IC > 0 and a top-3 return above equal-weight after modeled costs) and a kill rule. Be honest about the statistical power: at a realistic IC of about 0.03 on 100 names, significance takes **roughly 4-8 years**. The forward test protects you from a bad signal faster than it can prove a good one. A model upgrade changes the signal, so treat it as a new test.

**2. An earnings-event veto for trades you already make (costs nothing).** When a held or candidate stock files an 8-K Item 2.02 or holds a call, have Claude score tone and guidance with names anonymized (Glasserman & Lin). Use a strongly negative score only to skip or delay a buy the alpha or swing sleeve was about to make. That adds no extra orders. Log every event and measure the idiosyncratic return over the next 1, 5 and 20 days for vetoed versus kept events. Event-level tests accumulate faster, at about 400 events a year on 100 names. The evidence here is weak, though: press releases are priced by the open, transcript tone is a next-day effect, and large-cap PEAD has been zero since 2006. So the most likely finding is no value.

**3. Harden the paper-to-alpha pipeline instead of generating more alphas.** Count every formula and variant ever evaluated, and require t > 3 (Harvey-Liu-Zhu) or a deflated Sharpe instead of t > 2. Add AlphaAgent-style AST originality and complexity limits so extracted formulas can't be lightly perturbed copies of the same thing. For any LLM-*proposed* idea, run a memorization probe (does the model recall this ticker's outcome from the date alone?) before trusting an in-sample result. This is what Man Group describes doing, and it costs no trades.

**4. (Only if timestamped news is cheap) a clean historical backtest with point-in-time embeddings.** Take ChronoBERT vintages (the checkpoint dated before each test year), turn timestamped news into embeddings, fit a ridge model to *monthly* returns, and trade top-N monthly. This is the one way to backtest an LLM text signal without breaking the house rule. Expect something like Chen-Kelly-Xiu's value-weight monthly Sharpe of 0.4-0.6 *before* costs, likely lower on 100 names. Check first whether your Massive plan includes the news endpoint's history.

**Don't bother:** daily headline sentiment (it dies at your cost floor, and the edge sits in small caps), autonomous LLM agents (they lose to buy-and-hold in FINSABER), TSFM return forecasts (they don't beat a random walk), and LLM-generated formula mining without trial accounting.

---

## Sources

- Lopez-Lira & Tang, Can ChatGPT Forecast Stock Price Movements? https://arxiv.org/abs/2304.07619
- Chen, Kelly & Xiu, Expected Returns and Large Language Models. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416687 (slides: https://jacobslevycenter.wharton.upenn.edu/wp-content/uploads/2024/09/Kelly-WhartonJL.pdf)
- He, Lv, Manela & Wu, Chronologically Consistent Large Language Models. https://arxiv.org/abs/2502.21206
- Glasserman & Lin, Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. https://arxiv.org/abs/2309.17322
- Lehner & Lopez-Lira, ChatGPT as a Time Capsule. https://arxiv.org/abs/2604.21433
- Kim, Muhn & Nikolaev, Financial Statement Analysis with LLMs. https://arxiv.org/abs/2407.17866
- Wu, Akin, Martineau, Grégoire & Veneris, Extracting the Structure of Press Releases. https://arxiv.org/abs/2509.24254
- Yu et al., Fast Numbers, Slow Language. https://arxiv.org/abs/2606.29734
- Martineau, Rest in Peace Post-Earnings Announcement Drift. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607
- Lopez-Lira, Tang & Zhu, The Memorization Problem. https://arxiv.org/abs/2504.14765
- Sarkar & Vafa, Lookahead Bias in Pretrained Language Models. https://openreview.net/pdf?id=fn9cJkB86T
- Levy, Caution Ahead: Numerical Reasoning and Look-ahead Bias in AI Models (abstract only). https://onlinelibrary.wiley.com/doi/10.1111/1475-679x.70058
- Gao, Jiang & Yan, Detecting Lookahead Bias in LLM Forecasts. https://arxiv.org/abs/2512.23847
- Yan et al., DatedGPT. https://arxiv.org/abs/2603.11838
- Merchant & Levy, A Fast and Effective Solution to Look-ahead Bias in LLMs. https://arxiv.org/abs/2512.06607
- Li et al., Profit Mirage. https://arxiv.org/abs/2510.07920
- Tang et al., AlphaAgent. https://arxiv.org/abs/2502.16789
- Li et al., R&D-Agent(Q). https://arxiv.org/abs/2505.15155
- Xiao et al., TradingAgents. https://arxiv.org/abs/2412.20138
- Li, Kim, Cucuringu & Ma, FINSABER. https://arxiv.org/abs/2505.07078
- StockBench. https://arxiv.org/abs/2510.02209
- Agent Market Arena. https://arxiv.org/abs/2510.11695
- Nof1 Alpha Arena Season 1 results (ForkLog). https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/
- Rahimikia, Ni & Wang, Re(Visiting) Time Series Foundation Models in Finance. https://arxiv.org/abs/2511.18578
- Noguer i Alonso & Franklin, Pretrained TSFMs for Financial Return Forecasting. https://arxiv.org/abs/2606.27100
- Shi et al., Kronos. https://arxiv.org/abs/2508.02739
- Wu et al., BloombergGPT. https://arxiv.org/abs/2303.17564
- Li et al., Are ChatGPT and GPT-4 General-Purpose Solvers for Financial Text Analytics? https://arxiv.org/abs/2305.05862
- Man Group, What AI Can (and Can't Yet) Do for Alpha. https://www.man.com/insights/what-ai-can-do-for-alpha
- Bloomberg, Man Group Says Agentic AI Is Now Devising Quant Trading Signals (Jul 2025). https://www.bloomberg.com/news/articles/2025-07-10/man-group-says-agentic-ai-is-now-devising-quant-trading-signals
- Bloomberg, AQR Bets on Machine Learning as Asness Becomes AI Believer (Apr 2025). https://www.bloomberg.com/news/articles/2025-04-23/aqr-bets-on-machine-learning-as-cliff-asness-becomes-ai-believer
