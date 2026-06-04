"""
This script calculates and visualizes period returns for given stock symbols using Yahoo Finance data.
It takes start date, end date, and a comma-separated list of symbols (or a CSV file) as command-line arguments.

Arguments:
    sys.argv[1]: Start date (YYYY-MM-DD)
    sys.argv[2]: End date (YYYY-MM-DD)
    sys.argv[3]: Comma-separated stock symbols (e.g., "AAPL,MSFT") or a path to a CSV file containing symbols.

Output:
    - ./results/period_returns.csv: CSV file containing detailed return metrics for each symbol.
    - ./results/sma200.csv: CSV file with SP500TR's percentage from its 200-day Simple Moving Average.
    - ./results/period_returns_plot.png: A plot visualizing cumulative returns and SP500TR's SMA.
"""

import pandas as pd
import yfinance as yf
import sys
import numpy as np
import traceback
import warnings
from datetime import datetime
import os
import matplotlib.pyplot as plt

warnings.simplefilter(action="ignore", category=FutureWarning)

file_list = [
    os.path.join(os.getcwd(), "results", "period_returns.csv"),
    os.path.join(os.getcwd(), "results", "period_returns_0.csv"),
    os.path.join(os.getcwd(), "results", "failed_symbols.csv"),
]
for file in file_list:
    if os.path.exists(file):
        os.remove(file)

start_date = sys.argv[1]
end_date = sys.argv[2]
symbols_list = sys.argv[3]
if symbols_list.endswith(".csv") and os.path.exists(symbols_list):
    symbols_df = pd.read_csv(symbols_list)
    user_symbols_for_table = symbols_df["Symbol"].tolist()
else:
    user_symbols_for_table = [
        symbol.strip().upper() for symbol in symbols_list.split(",")
    ]

all_symbols_for_fetch = list(set(user_symbols_for_table + ["^SP500TR", "SPY", "^SPX"]))

df_master = yf.download(
    all_symbols_for_fetch,
    start="2000-01-01",
    end=datetime.now(),
    group_by="ticker",
    progress=False,
    auto_adjust=True,
)

# Lists to store calculated data for each symbol
all_symbol_data = []  # Stores cumulative returns, max drawdown, Sharpe, and Sortino
all_plot_data = []  # Stores data for plotting cumulative returns over time

# Loop through each symbol to calculate performance metrics
for symbol in user_symbols_for_table:
    if symbol not in df_master.columns.get_level_values(0):
        continue

    try:
        df = df_master[symbol].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.dropna()

        df = df.loc[start_date:end_date]
        if df.empty:
            print(
                f"No data for {symbol} between {start_date} and {end_date}. Skipping."
            )
            continue

        start_price = df["Close"].iloc[0]
        end_price = df["Close"].iloc[-1]
        percent_return = (end_price / start_price - 1) * 100

        peak = df["Close"].cummax()
        drawdowns = (df["Close"] - peak) / peak
        max_drawdown = drawdowns.min() * 100

        daily_ret = df["Close"].pct_change().dropna()
        years = (df.index[-1] - df.index[0]).days / 365.25
        n_obs = len(daily_ret)
        trading_days_per_year = n_obs / years
        ann_factor = np.sqrt(trading_days_per_year)

        if len(daily_ret) > 1:
            mean_daily = daily_ret.mean()
            std_daily = daily_ret.std()

            if std_daily > 0:
                sharpe = (mean_daily / std_daily) * ann_factor
            else:
                sharpe = np.nan

            downside_std = daily_ret[daily_ret < 0].std()
            if downside_std > 0:
                sortino = (mean_daily / downside_std) * ann_factor
            else:
                sortino = np.nan
        else:
            sharpe = np.nan
            sortino = np.nan

        all_symbol_data.append(
            {
                "Ticker": symbol,
                "Cummulative": percent_return,
                "MaxDrawDown": max_drawdown,
                "Sharpe": round(sharpe, 2),
                "Sortino": round(sortino, 2),
            }
        )

        cumulative_return_for_plot = (df["Close"] / df["Close"].iloc[0] - 1) * 100
        all_plot_data.append(
            {
                "symbol": symbol,
                "dates": df.index,
                "cumulative_return": cumulative_return_for_plot,
            }
        )

    except Exception as e:
        print(f"Error on {symbol}: {e}")
        traceback.print_exc()
        continue


# -------------------------------------------------------
# Now compute your $10k invested, CAGR, Years, etc., and write to period_returns_1.csv
# -------------------------------------------------------

# parse dates for CAGR
start_dt = datetime.strptime(start_date, "%Y-%m-%d")
end_dt = datetime.strptime(end_date, "%Y-%m-%d")

# create DataFrame from collected data & sort
top_75 = pd.DataFrame(all_symbol_data).sort_values("Cummulative", ascending=False)

# now assign Years as that constant
top_75["Years"] = (end_dt - start_dt).days / 365.25


# calculation MDD, % returns, $10k invested, etc.
top_75["Cummulative_float"] = top_75["Cummulative"].astype(float)
top_75["$10kInvested"] = (1 + top_75["Cummulative_float"] / 100) * 10000
top_75["$10kInvested"] = top_75["$10kInvested"].round(2)
top_75["CAGR_float"] = (
    (top_75["$10kInvested"] / 10000) ** (1 / top_75["Years"]) - 1
) * 100
init_investment = len(top_75) * 10000
final_investment = top_75["$10kInvested"].sum()
inv_return = (final_investment - init_investment) / init_investment * 100

# format values
top_75["Years"] = top_75["Years"].map("{:.2f}".format)
top_75["Cummulative"] = top_75["Cummulative_float"].round(2).map(lambda x: f"{x:,.2f}%")
top_75["MaxDrawDown"] = top_75["MaxDrawDown"].round(2).map(lambda x: f"{x:.2f}%")
top_75["CAGR"] = top_75["CAGR_float"].round(2).map(lambda x: f"{x:.2f}%")
top_75["$10kInvested"] = top_75["$10kInvested"].map(lambda x: f"${x:,.2f}")

# define your new column order
new_order = [
    "Ticker",
    "CAGR",
    "Cummulative",
    "$10kInvested",
    "Years",
    "MaxDrawDown",
    "Sharpe",
    "Sortino",
]

# prep summary rows for output to csv
additional = pd.DataFrame(
    {
        "Ticker": ["Initial Balance", "Final Balance", "Total Returns"],
        "CAGR": [f"${init_investment:,.2f}", None, None],
        "Cummulative": [None, f"${final_investment:,.2f}", None],
        "$10kInvested": [None, None, f"{inv_return:,.2f}%"],
    }
)

# prep df for output to csv
blank = pd.DataFrame({c: [""] for c in top_75.columns})
result_df = pd.concat([top_75, blank, additional], axis=0)
result_df = result_df.reindex(columns=new_order)

# output to csv
result_df.to_csv(
    os.path.join(os.getcwd(), "results", "period_returns.csv"), index=False
)

# print investment balances
os.system("cls" if os.name == "nt" else "clear")
print(f"\nHypothetical Investment of $10K per Ticker from {start_date} to {end_date}")
print(f"Initial Balance: ${init_investment:,.2f}")
print(f"Final Balance: ${final_investment:,.2f}")
print(f"Total Returns: {inv_return:,.2f}%\n\n\n")

# print only the dataframe (no blanks, no summary rows):
disp = top_75.copy()
disp = disp.reindex(columns=new_order)
disp = disp.fillna("")
print(disp.to_string(index=False))


# Calculate % from sma200 for multiple symbols
sma_symbols = ["^SP500TR", "SPY", "^SPX"]
df_sma_data = {}

for s_symbol in sma_symbols:
    if s_symbol in df_master.columns.get_level_values(0):
        df_temp = df_master[s_symbol].copy()
        df_temp.index = pd.to_datetime(df_temp.index, utc=True)
        df_temp = df_temp.dropna()
        df_temp["SMA200"] = df_temp["Close"].rolling(window=200).mean()
        df_temp["pct_from_sma200"] = (df_temp["Close"] / df_temp["SMA200"] - 1.0) * 100
        df_sma_data[s_symbol] = df_temp[["pct_from_sma200"]].loc[start_date:end_date]
    else:
        print(f"Warning: {s_symbol} data not found for SMA calculation.")

# Output SMA data for all specified symbols to csv
if df_sma_data:
    # Concatenate all SMA dataframes into a single dataframe
    df_all_sma = pd.concat(df_sma_data.values(), axis=1)
    # Rename columns to include symbol for clarity
    df_all_sma.columns = [f"{s}_pct_from_sma200" for s in df_sma_data.keys()]
    df_all_sma.to_csv(os.path.join(os.getcwd(), "results", "sma200.csv"))


# Plot disp, using x-axis as the date and y-axis as the daily cummulative % return
if all_plot_data:
    fig, ax = plt.subplots(figsize=(12, 7))
    for plot_data in all_plot_data:
        (line,) = ax.plot(
            plot_data["dates"],
            plot_data["cumulative_return"],
            label=plot_data["symbol"],
        )
        # Add text label at the end of the line
        ax.text(
            plot_data["dates"][-1],
            plot_data["cumulative_return"].iloc[-1],
            f"  {plot_data['symbol']}",
            verticalalignment="center",
            color=line.get_color(),
        )

    ax.set_title(f"Cumulative Return from {start_date} to {end_date}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Return (%)")
    ax.grid(True, which="both", linestyle="--", linewidth=0.5)

    # Create a secondary y-axis for percentage from 200-day SMA
    ax2 = ax.twinx()
    ax2.set_ylabel("% from 200-day SMA", color="tab:gray")
    for s_symbol, df_sma in df_sma_data.items():
        last_sma_value = df_sma["pct_from_sma200"].iloc[-1]
        ax2.plot(
            df_sma.index,
            df_sma["pct_from_sma200"],
            linestyle="--",
            label=f"{s_symbol} % from SMA200: {last_sma_value:.2f}%",
        )
    ax2.tick_params(axis="y", labelcolor="tab:gray")
    ax2.axhline(0, color="gray", linestyle="--", linewidth=0.7)

    # Add horizontal lines to indicate trigger points for strategy
    ax2.axhline(
        y=0.12 * 100,
        color="g",
        linestyle="--",
        lw=1,
        label=f"Take-Profit Trigger (+{0.12:.0%})",
    )
    ax2.axhline(
        y=-0.12 * 100,
        color="r",
        linestyle="--",
        lw=1,
        label=f"Leverage-Up Trigger (-{0.12:.0%})",
    )
    ax2.axhline(y=0, color="k", linestyle="-", linewidth=0.7)

    # Create legends upper left corner of the chart
    h1, l1 = ax2.get_legend_handles_labels()
    ax2.legend(h1, l1, loc="upper left")

    fig.tight_layout()
    plt.savefig(
        os.path.join(os.getcwd(), "results", "period_returns_plot.png"),
        dpi=150,
    )
else:
    print("No data available to plot.")
