# ETF P/E Calculation Guide

This repo includes `etf_pe.py`, a script for calculating a look-through P/E ratio for an ETF such as `SMH`.

## Quick Start

Run the default trailing twelve month calculation:

```bash
uv run python etf_pe.py SMH
```

Run the forward P/E version:

```bash
uv run python etf_pe.py SMH --method forward
```

Print fewer holding rows:

```bash
uv run python etf_pe.py SMH --top 5
```

Write holding-level details to a CSV:

```bash
uv run python etf_pe.py SMH --output-csv smh_pe_details.csv
```

## Core Formula

The script calculates the ETF as a weighted basket of company earnings yields:

```text
holding earnings yield = EPS / stock price
ETF earnings yield = sum(holding weight * holding earnings yield)
ETF P/E = 1 / ETF earnings yield
```

This is equivalent to calculating the weighted harmonic average of the holdings' P/E ratios when all holdings have positive earnings.

The default version is intended to answer:

```text
For this basket of stocks, how much am I paying for the basket's aggregate earnings?
```

## Default Data Sources

By default, the script uses:

- Holdings: `https://stockanalysis.com/etf/{ticker}/holdings/`
- Stock prices and EPS: Yahoo Finance data through `yfinance`

For `SMH`, the default run pulls the current holdings list, then fetches each holding's price and EPS from Yahoo Finance.

## Default TTM Method

Command:

```bash
uv run python etf_pe.py SMH
```

This uses Yahoo Finance trailing twelve month data:

- `trailingEps`
- current stock price
- fallback to `trailingPE` if EPS/price cannot be used

The script calculates:

```text
trailing earnings yield = trailingEps / current stock price
```

Then it calculates:

```text
ETF trailing P/E = 1 / sum(weight * trailing earnings yield)
```

The default TTM calculation includes negative EPS holdings. For example, if a holding has negative trailing EPS, its earnings yield is negative and it reduces the ETF's aggregate earnings. This is closest to a true basket-level calculation.

## Forward Method

Command:

```bash
uv run python etf_pe.py SMH --method forward
```

Yes: this uses Yahoo Finance forward data.

The script:

1. First tries Yahoo's `forwardEps`.
2. Calculates `forward earnings yield = forwardEps / current stock price`.
3. Calculates `ETF forward P/E = 1 / sum(weight * forward earnings yield)`.
4. Falls back to Yahoo's `forwardPE` if `forwardEps` is missing.

The script is not forecasting earnings itself. It is using Yahoo's consensus forward EPS / forward P/E fields.

For a growth-heavy ETF like `SMH`, forward P/E can be much lower than TTM P/E if analysts expect earnings to rise meaningfully.

## Positive-Only Method

Command:

```bash
uv run python etf_pe.py SMH --positive-only
```

This excludes holdings with zero or negative earnings yields.

Some data vendors do this because negative P/E ratios are awkward to average and can produce unintuitive results. For example, a company with negative EPS does not have a meaningful positive P/E multiple.

Tradeoff:

- Pro: easier to compare profitable holdings only
- Con: ignores the earnings drag from unprofitable holdings

Use this when trying to approximate a vendor that excludes negative P/E companies.

## P/E Cap Method

Command:

```bash
uv run python etf_pe.py SMH --cap-pe 60
```

This caps very high positive holding P/E values before aggregating.

Example: if a holding has a P/E of 180 and you use `--cap-pe 60`, the script treats that holding as if its P/E were 60.

Some vendors use caps so tiny earnings do not distort the portfolio ratio.

Tradeoff:

- Pro: reduces the effect of extreme high-P/E holdings
- Con: no longer reflects the exact current price divided by exact current earnings

You can combine it with `--positive-only`:

```bash
uv run python etf_pe.py SMH --positive-only --cap-pe 60
```

## Renormalize Method

Command:

```bash
uv run python etf_pe.py SMH --positive-only --renormalize
```

If holdings are excluded, `--renormalize` reweights the included holdings back to 100%.

Without `--renormalize`, excluded holdings simply do not contribute earnings yield.

With `--renormalize`, the calculation asks:

```text
What is the P/E of only the included slice of the ETF?
```

This is useful if you want to analyze the profitable portion of the ETF by itself.

## Custom Holdings CSV

Command:

```bash
uv run python etf_pe.py SMH --holdings-csv your_holdings.csv
```

The CSV needs:

- a symbol/ticker column
- a weight column

Accepted column names include:

- `Symbol`
- `Ticker`
- `Holding Ticker`
- `Weight`
- `% Weight`
- `% of Net Assets`
- `Percentage`

Weights are always interpreted as percentages. For example, `17`, `17.00`, and `17.00%` all mean a 17% ETF weight.

```csv
Symbol,Weight
NVDA,17.00%
TSM,10.49%
AVGO,7.95%
```

or:

```csv
Symbol,Weight
NVDA,17.00
TSM,10.49
AVGO,7.95
```

Do not use decimal weights like `0.1700` for 17%. With this script, `0.1700` means 0.17%.

## Useful Commands

Default trailing calculation:

```bash
uv run python etf_pe.py SMH
```

Forward calculation:

```bash
uv run python etf_pe.py SMH --method forward
```

Exclude negative earners:

```bash
uv run python etf_pe.py SMH --positive-only
```

Cap high P/E holdings at 60:

```bash
uv run python etf_pe.py SMH --cap-pe 60
```

Approximate a vendor-style method that excludes negative P/Es and caps high P/Es:

```bash
uv run python etf_pe.py SMH --positive-only --cap-pe 60
```

Analyze only the profitable slice:

```bash
uv run python etf_pe.py SMH --positive-only --renormalize
```

Use forward earnings and save details:

```bash
uv run python etf_pe.py SMH --method forward --output-csv smh_forward_pe.csv
```

Use your own holdings file:

```bash
uv run python etf_pe.py SMH --holdings-csv stocks_list/smh.csv
```

Show all available options:

```bash
uv run python etf_pe.py --help
```

## Which Version Should I Use?

For "what is SMH actually paying for earnings?", use the default:

```bash
uv run python etf_pe.py SMH
```

For "what does the market look like relative to expected future earnings?", use:

```bash
uv run python etf_pe.py SMH --method forward
```

For "why does this not match a website?", try vendor-style variants:

```bash
uv run python etf_pe.py SMH --positive-only
uv run python etf_pe.py SMH --positive-only --cap-pe 60
uv run python etf_pe.py SMH --positive-only --cap-pe 60 --renormalize
```

Different websites can disagree because they may use different choices for:

- trailing vs forward earnings
- GAAP vs adjusted EPS
- current holdings vs stale holdings
- including or excluding negative earners
- capping extreme P/E values
- renormalizing after exclusions
- using current price vs previous close

## Important Notes

This is an approximation. It is useful for understanding methodology and getting close to public ETF P/E figures, but it may not exactly match every data vendor.

The biggest reason for mismatches is not the formula. It is usually data methodology: which EPS number, which holdings date, whether negative earnings are excluded, and whether extreme P/Es are capped.
