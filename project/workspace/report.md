# Quantitative Research Process Post-Mortem Report

## 1. Version Evolution: Structural Changes and Driving Evidence

Across the three allowed versions (`v1`, `v2`, `v3`), every version was evaluated on the identical 9-point parameter grid (`mom_window` $\in \{63, 126, 189\} \times$ `top_n` $\in \{2, 3, 4\}$) to isolate structural effects from parameter tuning.

### Version 1 (`v1`) — Baseline Volume-Filtered Momentum
- **Structure:** Computed `mom_window`-day cumulative return from adjusted close and the ratio of 20-day to 120-day average dollar volume (`raw close * raw volume`). Assets were eligible if `momentum > 0` and `vol_ratio > 1.0`. Eligible assets were ranked by momentum, holding the top `top_n` at equal weight (`1 / top_n`), rebalanced monthly, with unfilled slots in cash.
- **Evidence from `v1` (`v1` Runs 1–9):**
  - Across all 9 runs, `v1` underperformed `plain_mom` (`dev_sharpe=0.5389`, `val_sharpe=0.9281`), `ew_bh` (`dev_sharpe=0.5524`, `val_sharpe=0.8707`), and `spy_bh` (`dev_sharpe=0.5261`, `val_sharpe=0.8817`).
  - Baseline `v1` Run 5 (`mom_window=126, top_n=3`) replicated the `volume_mom` benchmark (`dev_sharpe=0.4939`, `dev_cagr=0.064`, `dev_max_dd=-0.2564`, `dev_turnover=11.761`, `val_sharpe=0.5647`, `val_cagr=0.102`, `val_max_dd=-0.2901`).
  - `v1` Run 4 (`mom_window=126, top_n=2`) had the highest `v1` validation Sharpe (`0.5758`, `dev_sharpe=0.4735`, `dev_max_dd=-0.2777`), while `v1` Run 6 (`mom_window=126, top_n=4`) posted `dev_sharpe=0.4738` and `val_sharpe=0.5437`.
  - Shorter lookbacks (`v1` Runs 1–3, `mom_window=63`) failed in both splits (`dev_sharpe` `0.3240–0.4423`, `dev_max_dd` `-0.3976` to `-0.4411`, `val_sharpe` `0.2422–0.2801`, `dev_turnover` `11.320–12.266`). Longer lookbacks (`v1` Runs 7–9, `mom_window=189`) had competitive development Sharpe (`0.4839–0.4917`) but collapsed in validation (`val_sharpe` `0.3766–0.4526`).
  - In `/reviews/v1.md`, the critic diagnosed that gating on the 20d/120d volume ratio injected high-frequency noise into eligibility, inflating annual development turnover by 50%–68% (`10.917–12.266` vs. `plain_mom`'s `7.2800`) and causing a 120–130 bps CAGR drag when doubling costs from 10bps to 20bps.

### Version 2 (`v2`) — Risk-Adjusted Momentum (Replacing Volume Gate with Volatility Scaling)
- **Structural Change:** Removed the dollar-volume ratio gate entirely (`vol_short / vol_long > 1.0`) and replaced raw momentum ranking with **risk-adjusted momentum** (`momentum / realized_daily_return_volatility` over `mom_window` days), retaining the `momentum > 0` cash filter and monthly equal-weight top-`top_n` rebalancing.
- **Evidence from `v2` (`v2` Runs 1–9):**
  - Removing the volume filter and scaling by inverse volatility lifted validation Sharpe across all 9 grid points relative to `v1` (from `0.2422–0.5758` in `v1` to `0.6881–1.0127` in `v2`) and reduced development turnover from `10.917–12.266` down to `5.059–11.348`.
  - `v2` Run 5 (`mom_window=126, top_n=3`) achieved `dev_sharpe=0.5787` (`dev_cagr=0.0782`, `dev_max_dd=-0.2827`, `dev_turnover=7.1703`) and `val_sharpe=1.0127` (`val_cagr=0.2223`, `val_max_dd=-0.2901`), outperforming `plain_mom` in both development (`0.5787` vs. `0.5389`) and validation (`1.0127` vs. `0.9281`). `v2` Run 6 (`mom_window=126, top_n=4`) achieved `dev_sharpe=0.6024`, `dev_turnover=6.200`, and `val_sharpe=0.9610` (`val_max_dd=-0.3018`), and `v2` Run 4 (`mom_window=126, top_n=2`) posted `dev_sharpe=0.4828` and `val_sharpe=0.9221`.
  - However, `/reviews/v2.md` identified two remaining weaknesses: (1) unbuffered rank-boundary churn still kept `dev_turnover` at `7.170` on `v2` Run 5 (costing 80 bps between 10bps and 20bps and leaving 10bps `dev_cagr=0.078` below `spy_bh` `0.0847` and `ew_bh` `0.0904`), and (2) lookback instability persisted: `mom_window=189` (`v2` Runs 7–9) had the best development Sharpe (`0.6257` on Run 7, `0.5743` on Run 8, `0.5917` on Run 9) but dropped to `val_sharpe` `0.7133–0.7848` in validation, while `mom_window=63` (`v2` Runs 1–3) suffered `-0.4890` to `-0.5316` development max drawdowns (`dev_sharpe` `0.3591–0.4147`).

### Version 3 (`v3`) — Rank-Hysteresis Hold Buffer (`top_n + 1`)
- **Structural Change:** Added a rank-hysteresis hold buffer (`rank_buffer=1`) at monthly rebalances: any currently held asset that remained eligible (`momentum > 0`) and ranked within `top_n + 1` was retained before filling remaining slots with the highest-ranked non-held assets.
- **Evidence from `v3` (`v3` Runs 1–9):**
  - The hold buffer succeeded in cutting development turnover by 24%–47% across the grid (e.g., `v3` Run 5 at `mom_window=126, top_n=3` cut `dev_turnover` from `7.170` to `4.716`; `v3` Run 6 at `top_n=4` cut `dev_turnover` from `6.200` to `3.764`; `v3` Runs 7–9 at `mom_window=189` cut turnover to `2.660–4.183`) and raised development Sharpe across every single configuration (`v3` Runs 1–9 ranged from `0.4307` to `0.7605`, with `v3` Run 9 reaching `dev_sharpe=0.7605, dev_max_dd=-0.1915`).
  - However, as documented in `/reviews/v3.md`, delaying portfolio rotation degraded validation Sharpe across most of the grid (`v3` Run 5 dropped from `1.0127` to `0.9628`; `v3` Run 6 dropped from `0.9610` to `0.7759`; `v3` Runs 7–9 dropped to `0.6387–0.7793`), and even `v3`'s best validation configuration (`v3` Run 4, `mom_window=126, top_n=2`, `val_sharpe=0.9894`, `dev_sharpe=0.6390`) fell short of `v2` Run 5 (`1.0127`).

---

## 2. How the Selection Rule Decided Each Champion (Gate-by-Gate Analysis)

The pre-committed selection rule required a challenger to pass **all three** gates against the incumbent champion:
1. **Gate 1:** Validation Sharpe $\ge$ Incumbent Validation Sharpe
2. **Gate 2:** Validation Max Drawdown within 2 percentage points of Incumbent (`val_max_dd >= incumbent_val_max_dd - 0.02`)
3. **Gate 3:** Development Annual Turnover $\le 1.20 \times$ Incumbent Development Annual Turnover

| Transition | Incumbent Champion | Challenger Evaluated | Gate 1: `val_sharpe` | Gate 2: `val_max_dd` (within 2pp) | Gate 3: `dev_turnover` ($\le 1.2\times$) | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`v1` Decision** | None | `v1` Run 5 (`126, 3`) | `0.5647` (Baseline) | `-0.2901` (Baseline) | `11.761` (Baseline) | **`v1` Run 5 becomes initial champion** |
| **`v2` vs. `v1`** | `v1` Run 5 (`126, 3`) | `v2` Run 5 (`126, 3`) | **PASS** (`1.0127 >= 0.5647`) | **PASS** (`-0.2901 >= -0.3101`) | **PASS** (`7.170 <= 14.113`) | **`v2` Run 5 replaces `v1` as champion** |
| **`v3` vs. `v2` (Matched)** | `v2` Run 5 (`126, 3`) | `v3` Run 5 (`126, 3`) | **FAIL** (`0.9628 < 1.0127`) | **PASS** (`-0.2901 >= -0.3101`) | **PASS** (`4.716 <= 8.604`) | **Rejected; `v2` Run 5 remains champion** |
| **`v3` vs. `v2` (Best Val)** | `v2` Run 5 (`126, 3`) | `v3` Run 4 (`126, 2`) | **FAIL** (`0.9894 < 1.0127`) | **PASS** (`-0.2954 >= -0.3101`) | **PASS** (`6.100 <= 8.604`) | **Rejected; `v2` Run 5 remains champion** |

- **Why `v3` was rejected despite higher development metrics:** In `v3`, `dev_sharpe` improved at every single grid point (`0.5829` on `v3` Run 5 and `0.6390` on `v3` Run 4 vs. `0.5787` on `v2` Run 5, and up to `0.7605` on `v3` Run 9), and `dev_max_dd` improved from `-0.2827` (`v2` Run 5) to `-0.2435` (`v3` Run 5) and `-0.2174` (`v3` Run 4). However, development Sharpe is explicitly excluded from the selection gates, and every `v3` run (`v3` Runs 1–9, max `val_sharpe=0.9894`) failed Gate 1 against `v2` Run 5 (`val_sharpe=1.0127`).

---

## 3. Did the Revisions Improve the Research Case (Separately from Returns)?

Separating economic/statistical soundness from raw return numbers:
- **`v1` $\rightarrow$ `v2` genuinely improved the research case:**
  - *Complexity reduction:* `v1` had five parameters (`mom_window`, `vol_short`, `vol_long`, `vol_ratio_min`, `top_n`) and two distinct data dependencies (adjusted close and raw dollar volume). `v2` eliminated three parameters (`vol_short`, `vol_long`, `vol_ratio_min`) and the volume dependency, reducing degrees of freedom while computing return and volatility over the exact same `mom_window` lookback.
  - *Turnover and cost resilience:* Lowering annual turnover from `11.761` (`v1` Run 5) to `7.170` (`v2` Run 5) reduced the annual transaction cost drag by ~46 bps/year at 10bps.
  - *Cross-grid consistency:* Every single cell of the 9-configuration grid improved in validation Sharpe from `v1` to `v2`, confirming that removing the volume filter was not a single-point fluke on dev/val.
- **`v2` $\rightarrow$ `v3` weakened the out-of-sample research case despite achieving its mechanical goal:**
  - Mechanically, `v3`'s rank-hysteresis buffer did exactly what was hypothesized in `/reviews/v2.md`: it cut turnover by ~34% at `(126, 3)` (`v3` Run 5 `dev_turnover=4.716` vs. `v2` Run 5 `7.170`) and improved development Sharpe and drawdowns across all 9 runs.
  - However, it introduced a state-dependency parameter (`rank_buffer=1`) and exacerbated lookback-horizon divergence (`v3` Runs 7–9 at `mom_window=189` soared to `0.7145–0.7605` Sharpe in development while dropping to `0.6387–0.7793` in validation; `v3` Run 6 at `mom_window=126, top_n=4` dropped from `0.9610` in `v2` to `0.7759` in `v3`). The stage gate properly prevented this modification from entering the frozen strategy.
- **Unresolved structural fragility:** Neither `v2` nor `v3` resolved the sharp regime sensitivity of cross-sectional momentum lookbacks (`mom_window=189` winning development while `mom_window=126` won validation), signaling that single-lookback top-3 selection remained vulnerable to regime shifts.

---

## 4. Holdout Comparison: Frozen Strategy (`v2` Run 5) vs. Benchmarks

The frozen strategy (`v2` Run 5: `{"mom_window": 126, "top_n": 3}`) was evaluated once on the holdout period:

| Strategy / Benchmark | Holdout CAGR | Holdout Sharpe | Holdout Sortino | Holdout Max DD | Holdout Ann. Turnover |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Frozen `v2` (`mom_window=126, top_n=3`)** | **0.0596** | **0.4088** | **0.5586** | **-0.2248** | **8.5309** |
| **`spy_bh` (SPY Buy & Hold)** | 0.1106 | 0.6722 | 0.9728 | -0.2450 | 0.0000 |
| **`ew_bh` (Equal-Weight Buy & Hold)** | 0.0964 | 0.6254 | 0.8876 | -0.1823 | 0.0000 |
| **`plain_mom` (Plain Momentum)** | 0.0499 | 0.3522 | 0.4820 | -0.2370 | 8.1977 |
| **`volume_mom` (`v1` Baseline Equivalent)** | 0.1116 | 0.6721 | 0.9515 | -0.2370 | 10.6049 |

- **vs. `spy_bh`:** Frozen `v2` severely underperformed SPY buy-and-hold on CAGR (`5.96%` vs. `11.06%`, trailing by `-5.10` percentage points/year), Sharpe (`0.4088` vs. `0.6722`), and Sortino (`0.5586` vs. `0.9728`), with only a `2.02` percentage point smaller max drawdown (`-0.2248` vs. `-0.2450`) while paying `85` bps/year in transaction costs (`ann_turnover=8.5309`).
- **vs. `ew_bh`:** Frozen `v2` trailed equal-weight buy-and-hold on every single metric—lower CAGR (`5.96%` vs. `9.64%`), lower Sharpe (`0.4088` vs. `0.6254`), lower Sortino (`0.5586` vs. `0.8876`), and **worse** max drawdown (`-0.2248` vs. `-0.1823`).
- **vs. `plain_mom`:** Frozen `v2` outperformed `plain_mom` on the holdout across CAGR (`5.96%` vs. `4.99%`, +97 bps), Sharpe (`0.4088` vs. `0.3522`, +0.0566), Sortino (`0.5586` vs. `0.4820`), and max drawdown (`-0.2248` vs. `-0.2370`), with slightly higher holdout turnover (`8.5309` vs. `8.1977`). Thus, volatility-adjusted ranking (`v2`) beat raw return ranking (`plain_mom`) in all three splits (development, validation, and holdout), but cross-sectional 126-day momentum as a whole suffered a severe regime breakdown in the holdout (`plain_mom` Sharpe fell from `0.9281` in validation to `0.3522` in holdout; `v2` fell from `1.0127` to `0.4088`).

---

## 5. Did the Volume Filter Earn Its Turnover?

- **In Development and Validation (the only data visible during research): No.**
  - Comparing `v1` Run 5 (`volume_mom`) to `plain_mom`, adding the volume-ratio filter increased annual turnover by **+4.48x/year** in development (`11.7608` vs. `7.2800`) and **+5.20x/year** in validation (`10.8640` vs. `5.6637`).
  - Instead of earning a return premium for that extra turnover, the volume filter **destroyed** performance in both periods: development CAGR fell by `-113` bps (`0.0639` vs. `0.0752`, Sharpe `0.4939` vs. `0.5389`), and validation CAGR fell by **-1,034 bps/year** (`0.1018` vs. `0.2052`, Sharpe `0.5647` vs. `0.9281`). Over the entire pre-holdout sample, the volume filter had negative gross and net alpha.
- **In the Holdout: It paid off unexpectedly, contradicting both prior periods.**
  - On the holdout, `volume_mom` (`v1` Run 5) achieved `11.16%` CAGR and `0.6721` Sharpe (vs. `plain_mom`'s `4.99%` CAGR and `0.3522` Sharpe, and `v2`'s `5.96%` CAGR and `0.4088` Sharpe) despite `10.6049` annual turnover (`2.41x` higher than `plain_mom` and `2.07x` higher than `v2`).
  - However, because a filter that loses `-1.13%/yr` in development and `-10.34%/yr` in validation cannot honestly be defended ex ante, dropping the volume filter in `v2` was the only evidence-consistent decision available during the research process. Its holdout rebound reflects regime variance (where short-term volume breakouts rescued a failing 126-day momentum signal in the holdout window) rather than a stable, predictable edge across periods.

---

## 6. Self-Critique: Weak Decisions, Thin Evidence, and Luck

1. **Ignoring `v1` Run 4 vs. `v1` Run 5 when picking the `v1` representative config:**
   - In `v1`, Run 4 (`mom_window=126, top_n=2`) actually had a slightly higher validation Sharpe (`0.5758`) and slightly lower development turnover (`11.660`) than `v1` Run 5 (`mom_window=126, top_n=3`, `val_sharpe=0.5647`, `dev_turnover=11.761`). We selected Run 5 as the `v1` baseline champion because `(126, 3)` was the default specification and had higher `dev_sharpe` (`0.4939` vs. `0.4735`) and better `dev_max_dd` (`-0.2564` vs. `-0.2777`) and `val_max_dd` (`-0.2901` vs. `-0.2954`). While this did not affect the `v2` promotion (since `v2` Run 5 easily beat `v1` Run 4 on all three gates as well), our `v1` selection leaned on development metrics and defaults rather than strictly picking the validation-Sharpe leader.
2. **Selecting `v2` Run 5 (`val_sharpe=1.0127`) at a sharp local validation peak:**
   - In `v2`, validation performance peaked sharply at `mom_window=126` (`v2` Run 5 `val_sharpe=1.0127`, `v2` Run 6 `val_sharpe=0.9610`), whereas `mom_window=63` (`v2` Runs 1–3, `val_sharpe=0.6881–0.7216`) and `mom_window=189` (`v2` Runs 7–9, `val_sharpe=0.7133–0.7848`) were much weaker in validation. Conversely, in development, `v2` Run 5 (`dev_sharpe=0.5787`, `dev_cagr=0.0782`) trailed both `v2` Run 6 (`dev_sharpe=0.6024`) and `v2` Run 7 (`dev_sharpe=0.6257`, `dev_cagr=0.094`) and failed to beat passive `spy_bh` (`0.0847`) or `ew_bh` (`0.0904`) on development CAGR. Anchoring the champion on `val_sharpe=1.0127` effectively locked in a validation-regime sweet spot that reverted in the holdout (`sharpe=0.4088`).
3. **Wasting `v3` on a single-parameter turnover buffer instead of addressing lookback/concentration risk:**
   - The evidence in `/reviews/v2.md` clearly showed two problems: (a) turnover around `7.17x` and (b) stark disagreement between `mom_window=126` and neighbouring lookbacks (`63` and `189`). Choosing a simple `top_n + 1` hold buffer for `v3` only addressed (a) and did nothing to diversify across lookback windows. Because `v2` Run 5 already sat at an elevated validation Sharpe (`1.0127`), any sluggishness from holding deteriorating rank-4 positions inevitably caused `v3` to fail Gate 1 (`v3` Run 5 `val_sharpe=0.9628`).
4. **Where we got lucky and unlucky:**
   - *Lucky in Validation:* The validation split was an unusually strong trending environment for 126-day momentum (`plain_mom` achieved `20.52%` CAGR and `0.9281` Sharpe; `v2` Run 5 achieved `22.23%` CAGR and `1.0127` Sharpe with `0.0%` average cash). This inflated our confidence in `v2` Run 5.
   - *Unlucky (and exposed) in Holdout:* In the holdout, 126-day cross-sectional momentum suffered a broad drawdown/whipsaw regime (`plain_mom` collapsed to `4.99%` CAGR and `0.3522` Sharpe), while `v2`'s turnover rose from `6.84x` (val) and `7.17x` (dev) to `8.53x` (holdout). While `v2`'s volatility scaling preserved its ~`+0.057` Sharpe edge over `plain_mom` out of sample, that relative edge was far too small to prevent severe underperformance against simple passive benchmarks (`spy_bh` and `ew_bh`).
