import yfinance as yf
import pandas as pd
import argparse

def get_return_by_year(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(start="2010-01-01")
    if df.empty:
        return pd.Series(dtype=float)

    price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    df['Year'] = df.index.year
    annual_return = {}
    for year, group in df.groupby('Year'):
        group = group.sort_index()
        start_price = group.iloc[0][price_col]
        end_price = group.iloc[-1][price_col]
        if start_price > 0:
            annual_return[year] = ((end_price - start_price) / start_price) * 100
    result = pd.Series(annual_return)
    result.index.name = 'Year'
    return result

def get_max_drawdown_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(start="2010-01-01")
    if df.empty:
        return pd.Series(dtype=float)

    df['Year'] = df.index.year
    
    def calc_annual_dd(group):
        group = group.sort_index()
        group['Local_Peak'] = group['High'].cummax()
        group['Local_DD'] = (group['Low'] - group['Local_Peak']) / group['Local_Peak']
        return group['Local_DD'].min() * 100

    annual_max_drawdown = df.groupby('Year').apply(calc_annual_dd)
    return annual_max_drawdown

def main():
    parser = argparse.ArgumentParser(description="Calculate annual max drawdown for a ticker.")
    parser.add_argument("--ticker", type=str, help="Ticker symbol")
    parser.add_argument("--compare", nargs="+", type=str, help="List of tickers to compare")
    args = parser.parse_args()

    if args.compare:
        print(f"Comparing: {', '.join(args.compare)}")
        comparison_df = pd.DataFrame()
        for t in args.compare:
            series = get_max_drawdown_data(t)
            comparison_df[t] = series
        
        # reset_index() moves 'Year' from the index to a regular column
        # index=False removes the numeric row index from the output
        print(comparison_df.reset_index().to_string(index=False, float_format="{:.2f}%".format))
    elif args.ticker:
        return_series = get_return_by_year(args.ticker)
        dd_series = get_max_drawdown_data(args.ticker)
        combined = pd.DataFrame({'Return': return_series, 'Max Drawdown': dd_series})
        combined = combined.rename_axis('Year').reset_index()
        print(f"Annual Return & Max Drawdown for {args.ticker}:")
        print(combined.to_string(index=False, float_format="{:.2f}%".format))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

