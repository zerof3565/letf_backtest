import yfinance as yf
import pandas as pd
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def get_intraday_trailing_dd(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(start="2010-01-01")
    if df.empty:
        return pd.DataFrame()

    df['Peak_High'] = df['High'].cummax()
    df['Intraday_Trailing_DD'] = (df['Low'] - df['Peak_High']) / df['Peak_High'] * 100
    df = df.tail(252)

    df = df.reset_index()
    df['Date'] = df['Date'].dt.date

    return df[['Date', 'Intraday_Trailing_DD']]


def main():
    parser = argparse.ArgumentParser(description="Calculate daily intraday trailing drawdown for a ticker.")
    parser.add_argument("--ticker", type=str, help="Ticker symbol")
    parser.add_argument("--output", type=str, default="intraday_trailing_dd.png", help="Output PNG filename")
    args = parser.parse_args()

    if args.ticker:
        data = get_intraday_trailing_dd(args.ticker)
        if data.empty:
            print("No data available.")
            return

        print(f"Daily Intraday Trailing DD for {args.ticker} (last 252 trading days):")
        print(data.to_string(index=False, float_format="{:.2f}%".format))

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.fill_between(data['Date'], data['Intraday_Trailing_DD'], 0, color='steelblue')
        ax.axhline(y=0, color='black', linewidth=0.8)
        ax.set_title(f"Intraday Trailing DD - {args.ticker} (Last 252 Trading Days)", fontsize=14)
        ax.set_xlabel("Date")
        ax.set_ylabel("Intraday Trailing DD (%)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.xticks(rotation=45)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        fig.savefig(args.output, dpi=150)
        print(f"Chart saved to {args.output}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
