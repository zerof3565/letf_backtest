# LETF Backtest

200-SMA rotation backtest engine for leveraged ETFs.

## Quick Start

```bash
uv run python letf10.py -s 2022-01-01 -e 2026-05-12 -l TQQQ -f SPY -o TQQQ
```

## Required Arguments

| Flag | Role | Condition |
|------|------|-----------|
| `-s` | Start date | YYYY-MM-DD |
| `-e` | End date | YYYY-MM-DD |
| `-l` | Long symbol | 100% allocated when SPY > 200 SMA |
| `-f` | Safe symbol | 100% allocated when SPY < 200 SMA |
| `-o` | Other symbol | 100% allocated when SPY is 10% below 200 SMA |

## Scripts

| Script | Half-state (price >10% above SMA200) |
|--------|--------------------------------------|
| `letf10.py` | 50% long / 50% safe |
| `letf10_full_rotate.py` | 100% safe (full exit) |

## State Machine

- **long** — SPY > SMA200 → 100% long symbol
- **safe** — SPY < SMA200 → 100% safe symbol
- **other** — SPY < SMA200 by 10% → 100% other symbol
- **half** — SPY > SMA200 by 10% while in long → configurable split
