import pandas as pd
from yahooquery import Ticker
import sys
import os
import numpy as np




#   Delete old csv files before continuing
file_list = ["./results/period_returns.csv", "./results/period_returns_0.csv", "./results/period_returns_1.csv"]
for file in file_list:
    if os.path.exists(file):
        os.remove(file)




#   Load the list of symbols
# Handle both CSV files and single symbol inputs
symbols_list = sys.argv[1]
if symbols_list.endswith('.csv'):
    print('CSV file detected')
    symbols = pd.read_csv(symbols_list)
    # Clean NASDAQ CSV specific formatting only if Name column exists
    if len(symbols) > 510 and 'Name' in symbols.columns:
        symbols = symbols[symbols['Name'].apply(lambda x: x.split()[-2:] == ['Common', 'Stock'])]
        symbols = symbols[symbols['Symbol'] != 'DAY']
    symbols = symbols.set_index('Symbol')
else:
    symbols = [s.upper() for s in symbols_list.split(',')]
    print(f'Processing symbols: {", ".join(symbols)}')
    symbols = pd.DataFrame({'Symbol': symbols})
    symbols = symbols.set_index('Symbol')
try:
    symbols = symbols.index.tolist()
except NameError:
    symbols = symbols_list

    #   setup for async download
market_symbol = '^SP500TR'
symbols.append(market_symbol)
tickers = Ticker(symbols, asynchronous=True)
stocks = tickers.history(period='1y', interval='1d', adj_timezone=False)
market = stocks.loc[market_symbol]
summary_detail = tickers.summary_detail


# Calculate Beta (1Yr Daily)
def calc_beta(stock):
    #   calculating daily returns percentage for SP500TR and for the stock
    stock_returns = (list(stock['close'].pct_change()))[1:]
    market_returns = (list(market['close'].pct_change()))[1:]
    covariance = np.cov(stock_returns, market_returns)[0, 1]
    variance = np.var(market_returns)
    #   calculate the beta for the stock
    beta = covariance / variance
    return beta

results = []
for symbol in symbols:
    symbol = symbol.upper()
    if symbol == '^SP500TR':
        continue
    else:
        print(f'Working on {symbol}')

    # get ipo date
    try:
        inception = Ticker(symbol).history(period='max', interval='1d').index[0][1].strftime('%Y-%m-%d')
    except Exception:
        inception = 'N/A'

    # Get proper market cap/NAV for ETFs vs stocks
    try:
        asset_type = Ticker(symbol).quote_type[symbol].get('quoteType', '').lower()
        sd = summary_detail[symbol]

        if 'etf' in asset_type:
            # Try multiple ETF-specific fields
            # Handle null values in navPrice and sharesOutstanding
            market_cap = sd.get('totalAssets') or sd.get('totalNav') or \
                        (sd.get('navPrice', 0) * sd.get('sharesOutstanding', 0))
            # Get yield and expense ratio for ETFs
            yield_etf = sd.get('yield') or sd.get('trailingAnnualDividendYield') or 'N/A'
            fund_profile = tickers.fund_profile[symbol]
            expense_ratio = fund_profile.get('feesExpensesInvestment', {}).get('annualReportExpenseRatio') or 'N/A'
        else:
            market_cap = sd.get('marketCap', 0)
            yield_etf = sd.get('dividendYield', 'N/A')
            expense_ratio = 'N/A'

        # Final fallback using price and volume
        if market_cap in (0, None):
            price = stocks.loc[symbol]['close'].iloc[-1]
            volume = sd.get('averageDailyVolume10Day', sd.get('regularMarketVolume', 0))
            market_cap = price * volume  # Approximation when official data missing

    except Exception as e:
        print(f"Error getting market cap for {symbol}: {str(e)}")
        market_cap = 0

    # Calculate Beta
    try:
        beta = round(calc_beta(stocks.loc[symbol]), 2)
    except Exception as e:
        print(f'{e}')
        beta = 0

    results.append([symbol, inception, market_cap, beta, yield_etf, expense_ratio])

# Create DataFrame from results
market_cap_df = pd.DataFrame(results, columns=["Ticker", "Inception", "MarketCap", "Beta", "Yield", "ExpenseRatio"]).sort_values("MarketCap", ascending=False)

#   calculate market cap and selection %
marketcap_selection_count = 10
marketcap_sum = market_cap_df['MarketCap'].sum()
marketcap_selection = market_cap_df['MarketCap'].head(marketcap_selection_count).sum()

#   output to csv file before visualization process begins
market_cap_df.set_index('Ticker').to_csv(os.path.join(os.getcwd(), "yquery", "results", "period_returns.csv"))

#   Format MarketCap for display
market_cap_df['MarketCap'] = market_cap_df['MarketCap'].map(lambda x: f'${x:,.0f}')

#   drop columns and set index to Ticker
market_cap_df['Yield'] = market_cap_df['Yield'].map(lambda x: f'{x:.2%}' if isinstance(x, (float, np.float64)) else x)
market_cap_df['ExpenseRatio'] = market_cap_df['ExpenseRatio'].map(lambda x: f'{x:.2%}' if isinstance(x, (float, np.float64)) else x)
print(f'\n\n{market_cap_df.to_string(index=False)}')
print(f'\nTotal Cap: ${marketcap_sum:,.0f}')
# Handle division by zero case
if marketcap_sum > 0:
    print(f'Percent of Total Cap: {marketcap_selection/marketcap_sum*100:,.2f}%\n')
else:
    print('Percent of Total Cap: N/A (zero total market cap)')
