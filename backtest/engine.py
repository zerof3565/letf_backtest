"""Backtest engine for 200-SMA rotation strategies."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from yahooquery import Ticker


@dataclass
class BacktestConfig:
    long_sym: str
    safe_sym: str
    other_sym: str
    start_date: str
    end_date: str
    p_up: float = 0.10
    p_down: float = 0.10
    initial_capital: float = 10_000
    half_weights: tuple[float, float, float] = (0.5, 0.5, 0.0)
    warmup_days: int = 293


def build_cli(
    description: str = "Run a 200-SMA rotation backtest.",
) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("-s", "--start", required=True, help="Start date (YYYY-MM-DD)")
    p.add_argument("-e", "--end", required=True, help="End date (YYYY-MM-DD)")
    p.add_argument("-l", "--long", required=True, dest="long_sym", help="Symbol for long state (price > SMA200)")
    p.add_argument("-f", "--safe", required=True, dest="safe_sym", help="Symbol for safe state (price < SMA200)")
    p.add_argument("-o", "--other", required=True, dest="other_sym", help="Symbol for other state (price 10% below SMA200)")
    return p


def parse_cli(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        long_sym=args.long_sym.strip().upper(),
        safe_sym=args.safe_sym.strip().upper(),
        other_sym=args.other_sym.strip().upper(),
        start_date=args.start.strip(),
        end_date=args.end.strip(),
    )


def fetch_data(symbols: list[str], warmup_start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    hist = (
        Ticker(symbols)
        .history(period="max", interval="1d")[["close", "adjclose"]]
        .reset_index()
    )
    hist["date"] = pd.to_datetime(hist["date"], utc=True).dt.normalize().dt.tz_localize(None)
    hist = hist[hist["date"] >= warmup_start].copy()

    adj = (
        hist.pivot(index="date", columns="symbol", values="adjclose")
        .sort_index()
        .dropna()
    )

    close = hist.pivot(index="date", columns="symbol", values="close").sort_index()

    return adj, close


def compute_weights(
    close: pd.Series,
    sma: pd.Series,
    p_up: float,
    p_down: float,
    half_weights: tuple[float, float, float],
) -> pd.DataFrame:
    df = pd.DataFrame({"close": close, "sma": sma}).dropna()
    n = len(df)
    w_long = np.zeros(n)
    w_safe = np.zeros(n)
    w_other = np.zeros(n)

    current = "safe"

    for i, (price, ma) in enumerate(zip(df["close"], df["sma"])):
        up_high = ma * (1 + p_up)
        down_low = ma * (1 - p_down)

        if price < down_low:
            state = "other"
        elif current == "other":
            state = "long" if price > ma else "other"
        elif price < ma:
            state = "safe"
        elif current == "long" and price > up_high:
            state = "half"
        elif current == "half":
            state = "half"
        elif price > ma:
            state = "long"
        else:
            state = "safe"

        if state == "other":
            w_long[i], w_safe[i], w_other[i] = 0.0, 0.0, 1.0
        elif state == "safe":
            w_long[i], w_safe[i], w_other[i] = 0.0, 1.0, 0.0
        elif state == "long":
            w_long[i], w_safe[i], w_other[i] = 1.0, 0.0, 0.0
        else:
            w_long[i], w_safe[i], w_other[i] = half_weights

        current = state

    out = pd.DataFrame({"w_long": w_long, "w_safe": w_safe, "w_other": w_other}, index=df.index)
    out = out.shift(1)
    out.iloc[0] = 0.0
    return out


def compute_metrics(returns: pd.Series, initial_capital: float) -> dict:
    equity = initial_capital * (1 + returns).cumprod()
    n_days = len(returns)
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    tdpy = n_days / years

    cagr = (equity.iloc[-1] / initial_capital) ** (1 / years) - 1
    tot_return = equity.iloc[-1] / initial_capital - 1

    mu = returns.mean()
    sigma = returns.std()
    down_rets = returns[returns < 0]
    down_std = down_rets.std()

    sharpe = mu / sigma * np.sqrt(tdpy) if sigma > 0 else 0.0
    ann_vol = sigma * np.sqrt(tdpy) * 100
    ann_ret = mu * tdpy * 100
    sortino = (mu * tdpy) / (down_std * np.sqrt(tdpy)) if down_std > 0 else 0.0

    roll_max = equity.cummax()
    drawdown = equity / roll_max - 1
    max_dd = drawdown.min() * 100

    trough_date = drawdown.idxmin()
    peak_date = equity.loc[:trough_date].idxmax()
    peak_equity = equity.loc[peak_date]
    trough_equity = equity.loc[trough_date]

    return {
        "equity": equity,
        "drawdown": drawdown,
        "max_dd": max_dd,
        "cagr": cagr,
        "tot_return": tot_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "ann_vol": ann_vol,
        "ann_ret": ann_ret,
        "n_days": n_days,
        "years": years,
        "tdpy": tdpy,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "peak_equity": peak_equity,
        "trough_equity": trough_equity,
    }


def print_results(cfg: BacktestConfig, metrics: dict, days_long: int, days_safe: int, days_other: int) -> None:
    print("---------------------------------------------------------------")
    print(f"Long/Safe/Other Symbols:      {cfg.long_sym}/{cfg.safe_sym}/{cfg.other_sym}")
    print(f"Period:                       {metrics['equity'].index[0].date()} → {metrics['equity'].index[-1].date()}")
    print(f"Trading days:                 {metrics['n_days']}")
    print(f"Total years:                  {metrics['years']:.2f}")
    print(f"Days in:                      {cfg.long_sym} is {days_long}, {cfg.safe_sym} is {days_safe}, {cfg.other_sym} is {days_other}")
    print("---------------------------------------------------------------")
    print(f"CAGR:                         {metrics['cagr']:.2%}")
    print(f"Total return:                 {metrics['tot_return']:.2%}")
    print(f"Start capital:                ${cfg.initial_capital:,.2f}")
    print(f"End capital:                  ${metrics['equity'].iloc[-1]:,.2f}")
    print(f"Sharpe:                       {metrics['sharpe']:.2f}")
    print(f"Sortino:                      {metrics['sortino']:.2f}")
    print(f"Annual volatility:            {metrics['ann_vol']:.2f}%")
    print(f"Annual return:                {metrics['ann_ret']:.2f}%")
    print("---------------------------------------------------------------")
    print(f"Max drawdown:                 {metrics['max_dd']:.2f}%")
    print(f"Peak→Trough days:             {(metrics['trough_date'] - metrics['peak_date']).days}")
    print(f"Peak date:                    {metrics['peak_date'].date()}")
    print(f"Trough date:                  {metrics['trough_date'].date()}")
    print(f"Peak equity:                  ${metrics['peak_equity']:,.2f}")
    print(f"Trough equity:                ${metrics['trough_equity']:,.2f}")


def plot_results(cfg: BacktestConfig, equity: pd.Series, pct_sma: pd.Series, p_up: float, p_down: float, output_path: str) -> None:
    fig, ax1 = plt.subplots(figsize=(12, 7))
    fig.suptitle(f"{cfg.long_sym} / {cfg.safe_sym} / {cfg.other_sym}")

    color = "tab:blue"
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Equity ($)", color=color)
    final_equity = equity.iloc[-1]
    initial_equity = equity.iloc[0]
    cum_pct = ((final_equity - initial_equity) / initial_equity) * 100
    ax1.plot(
        equity.index, equity,
        color=color, lw=2,
        label=f"Equity (Return: {cum_pct:.2f}%, Final: ${final_equity:,.2f})",
    )
    ax1.tick_params(axis="y", labelcolor=color)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax1.grid(True, which="both", linestyle="--", linewidth=0.5)

    ax2 = ax1.twinx()
    color = "black"
    ax2.set_ylabel("% from 200-day SMA", color=color)
    ax2.plot(
        pct_sma.index, pct_sma,
        color=color, lw=1.5, linestyle=":",
        label=f"% from SMA (Final: {pct_sma.iloc[-1]:.2f}%)",
    )
    ax2.tick_params(axis="y", labelcolor=color)
    ax2.axhline(y=p_up * 100, color="g", linestyle="--", lw=1, label=f"Take-Profit (+{p_up:.0%})")
    ax2.axhline(y=-p_down * 100, color="r", linestyle="--", lw=1, label=f"Hedge Trigger (-{p_down:.0%})")
    ax2.axhline(y=0, color="k", linestyle="-", linewidth=0.7)

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left")

    fig.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close(fig)


def export_csv(cfg: BacktestConfig, df: pd.DataFrame, path: str) -> None:
    out = df.reset_index()
    out["daily_ret"] = out["daily_ret"].map("{:.4f}".format)
    out.to_csv(path, index=False, float_format="%.2f")


def run_backtest(cfg: BacktestConfig) -> None:
    print("\nMake sure start date is within the inception date range for all symbols\n")

    user_start = pd.to_datetime(cfg.start_date)
    user_end = pd.to_datetime(cfg.end_date)
    if user_end < user_start:
        raise ValueError("End date is before start date!")

    unique_symbols = [cfg.long_sym, cfg.safe_sym, cfg.other_sym]
    symbols = ["SPY"] + list(dict.fromkeys(unique_symbols))
    warmup_start = user_start - timedelta(days=cfg.warmup_days)

    adj, close = fetch_data(symbols, warmup_start.isoformat())
    sma200 = close["SPY"].rolling(window=200).mean()

    spx = close["SPY"].to_frame("SPY_close").join(sma200.to_frame("SMA200"))
    spx = spx.loc[cfg.start_date : cfg.end_date].dropna()

    weights = compute_weights(spx["SPY_close"], spx["SMA200"], cfg.p_up, cfg.p_down, cfg.half_weights)

    rets = adj.pct_change().loc[weights.index]
    strat_rets = (
        weights["w_long"] * rets[cfg.long_sym]
        + weights["w_safe"] * rets[cfg.safe_sym]
        + weights["w_other"] * rets[cfg.other_sym]
    ).fillna(0.0)

    metrics = compute_metrics(strat_rets, cfg.initial_capital)

    spx["daily_ret"] = strat_rets
    spx["equity"] = metrics["equity"]
    spx["pct_from_sma200"] = (spx["SPY_close"] / spx["SMA200"] - 1.0) * 100
    spx = spx.join(weights)

    for role, ticker in [("long", cfg.long_sym), ("safe", cfg.safe_sym), ("other", cfg.other_sym)]:
        spx[f"{ticker}_value"] = metrics["equity"] * spx[f"w_{role}"]

    days_long = (spx["w_long"] > 0).sum()
    days_safe = (spx["w_safe"] > 0).sum()
    days_other = (spx["w_other"] > 0).sum()

    results_dir = os.path.join(os.getcwd(), "yquery", "results")
    os.makedirs(results_dir, exist_ok=True)

    csv_path = os.path.join(results_dir, "strategy_output.csv")
    export_csv(cfg, spx, csv_path)

    print_results(cfg, metrics, days_long, days_safe, days_other)

    plot_path = os.path.join(results_dir, f"{cfg.long_sym}_{cfg.safe_sym}_{cfg.other_sym}.png")
    plot_results(cfg, metrics["equity"], spx["pct_from_sma200"], cfg.p_up, cfg.p_down, plot_path)
