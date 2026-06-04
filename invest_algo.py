import pandas as pd
import csv
import sys
import os
from yahooquery import Ticker
import numpy as np




# Calculate Beta (1Yr Daily)
def calc_beta(stock_history, market_history):
    #   calculating daily returns percentage for SPY and for the stock
    stock_returns = (list(stock_history['close'].pct_change()))[1:]
    market_returns = (list(market_history['close'].pct_change()))[1:]
    #   calculate the covariance and variance of the returns
    covariance = np.cov(stock_returns, market_returns)[0, 1]
    variance = np.var(market_returns)
    #   calculate the beta for the stock
    beta = covariance / variance
    return beta


#   Delete old csv files before continuing
file_list = ["./results/period_returns.csv", "./results/period_returns_0.csv", "./results/period_returns_1.csv"]
for file in file_list:
    if os.path.exists(file):
        os.remove(file)




#   Load the list of symbols
symbols_list = sys.argv[1]
if symbols_list.endswith('.csv'):
    print('CSV file detected')
else:
    symbols_list = symbols_list.split(',')
    symbols_list = [symbol.upper() for symbol in symbols_list]
    #   read all tickers and store into a list of symbols
try:
    symbols = pd.read_csv(symbols_list)
    df = symbols.copy()
    df = df.set_index('Symbol')
except Exception:
    print('no csv file detected')
try:
    symbols = list(symbols['Symbol'])
except NameError:
    symbols = symbols_list




# INIT CSV TO WRITE RESULTS
with open(os.path.join(os.getcwd(), "yquery", "results", "period_returns.csv"), "w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(["Symbol", "EPS", "PE", "EPS_ENY", "PE_ENY", "P2S_ENY","EPSG_ENY", "REV_ENY", "REVG_ENY", "MarketCap", "Beta", "ERDate"])




# Filter stocks with a screener
screener = input("Run Screener? Press 1 for Y and 2 for N: ")




# FIND SYMBOLS THAT MATCHES CRITERIAS
for index, symbol in enumerate(symbols, start=1):
    symbol = symbol.upper()
    print(f'Working on {symbol} ({index}/{len(symbols)})')

    #   Get financial data
    stock = Ticker(symbol)

    #   Get financial statements
    try:
        stock_quarterly_balancesheet = (stock.balance_sheet(frequency='q').T).iloc[:, ::-1]
    except Exception as e:
        continue
    stock_quarterly_incomestmt = (stock.income_statement(frequency='q', trailing=False).T).iloc[:, ::-1]

    #   Get earnings estimates
    try:
        next_year = next(item for item in stock.earnings_trend[symbol]['trend'] if item.get('period') == '+1y')
    except Exception as e:
        continue
    eps_estimate_ny = next_year['earningsEstimate']['avg']
    eps_growth_estimate_ny = next_year['earningsEstimate']['growth']
    rev_estimate_ny = next_year['revenueEstimate']['avg']
    rev_growth_estimate_ny = next_year['revenueEstimate']['growth']
    try:
        pe_estimate_ny = stock.price[symbol]['regularMarketPrice'] / eps_estimate_ny
    except Exception as e:
        pe_estimate_ny = 0.00000001
        eps_estimate_ny = 0.0000001


    #   Get profitability metrics
    earnings_per_share = stock_quarterly_incomestmt.iloc[:, :4].loc['BasicEPS'].sum(axis=0)
    price_per_earnings = stock.price[symbol]['regularMarketPrice'] / earnings_per_share

    #   Get market cap
    summary_detail = stock.summary_detail
    market_cap = (summary_detail[symbol])['marketCap']

    #   Calculate price2sales estimate
    try:
        price2sales_estimate_ny = market_cap / rev_estimate_ny
    except Exception as e:
        price2sales_estimate_ny = 0.00000001
        rev_estimate_ny = 0.00000001

    #       er date
    # er_date = str(stock_quarterly_balancesheet.loc["asOfDate"][0])[:-8]
    er_date = stock_quarterly_balancesheet.iloc[0, 0].strftime('%Y-%m-%d')

    #   beta
    try:
        stock_history = stock.history(period='1y', interval='1d', adj_timezone=False)
        market_history =Ticker('^SP500TR').history(period='1y', interval='1d', adj_timezone=False)
        beta = calc_beta(stock_history, market_history)
    except Exception:
        beta = 0


    #   Set stock screener factors
    if screener == '1':
        # if (
        #     # beta < 0.85 or
        #     # eps_estimate_ny <= 0 or
        #     # pe_estimate_ny <= 0 or
        #     # (eps_estimate_ny / earnings_per_share) < 1.25 or
        #     # (price_per_earnings / pe_estimate_ny) < 1.25 or
        #     # (pe_estimate_ny / eps_estimate_ny) > 1.75
        # ):
        #     continue
        # else:
        #     print(f"{symbol} --> Matched")

        if (eps_estimate_ny / earnings_per_share) < 1.95:
            continue
        elif (price_per_earnings / pe_estimate_ny) < 1.95:
            continue
        else:
            print(f"{symbol} --> Matched")

    #   write result to csv
    with open(os.path.join(os.getcwd(), "yquery", "results", "period_returns.csv"), "a", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([symbol, earnings_per_share, price_per_earnings, eps_estimate_ny, pe_estimate_ny, \
                            price2sales_estimate_ny, eps_growth_estimate_ny, rev_estimate_ny, rev_growth_estimate_ny, \
                            market_cap, beta, er_date])




# VISUALIZE THE RESULT
top_75 = pd.read_csv(os.path.join(os.getcwd(), "yquery", "results", "period_returns.csv")).sort_values("MarketCap", ascending=False)

#   print to console the results
top_75 = top_75.set_index('Symbol')

# Rename columns and format values
if 'EPS' in top_75.columns:
    top_75 = top_75.rename(columns={'EPS': 'EPS_ttm'})
    top_75['EPS_ttm'] = top_75['EPS_ttm'].apply(lambda x: f"{float(x):.2f}")

if 'PE' in top_75.columns:
    top_75 = top_75.rename(columns={'PE': 'PE_ttm'})
    top_75['PE_ttm'] = top_75['PE_ttm'].apply(lambda x: f"{float(x):.2f}")

if 'REV_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'REV_ENY': 'Rev_est'})
    top_75['Rev_est'] = top_75['Rev_est'].apply(lambda x: f"${float(x):,.0f}")

if 'REVG_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'REVG_ENY': 'Rev_G_est'})
    top_75['Rev_G_est'] = top_75['Rev_G_est'].apply(lambda x: f"{float(x) * 100:.2f}%")

if 'EPS_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'EPS_ENY': 'EPS_est'})
    top_75['EPS_est'] = top_75['EPS_est'].apply(lambda x: f"{float(x):.2f}")

if 'EPSG_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'EPSG_ENY': 'EPS_G_est'})
    top_75['EPS_G_est'] = top_75['EPS_G_est'].apply(lambda x: f"{float(x) * 100:.2f}%")

if 'PE_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'PE_ENY': 'PE_fwd'})
    top_75['PE_fwd'] = top_75['PE_fwd'].apply(lambda x: f"{float(x):.2f}")

if 'P2S_ENY' in top_75.columns:
    top_75 = top_75.rename(columns={'P2S_ENY': 'P2S_est'})
    top_75['P2S_est'] = top_75['P2S_est'].apply(lambda x: f"{float(x):.2f}")

if 'MarketCap' in top_75.columns:
    top_75 = top_75.rename(columns={'MarketCap': 'MarketCap'})
    top_75['MarketCap'] = top_75['MarketCap'].apply(lambda x: f"${float(x):,.0f}")

if 'Beta' in top_75.columns:
    top_75 = top_75.rename(columns={'Beta': 'Beta'})
    top_75['Beta'] = top_75['Beta'].apply(lambda x: f"{float(x):.2f}")


# format for general use
top_75.index.name = None
print('\n')
print(top_75)
print('\n')









# format only for discord
# 1. Load and set index
top_75 = pd.read_csv(os.path.join(os.getcwd(), "yquery", "results", "period_returns.csv")).sort_values("MarketCap", ascending=False)
top_75 = top_75.set_index('Symbol')

# 2. Rename columns while they are still NUMERIC (don't format to strings yet)
rename_map = {
    'EPS': 'EPS_ttm',
    'PE': 'PE_ttm',
    'REV_ENY': 'Rev_est',
    'REVG_ENY': 'Rev_G%',
    'EPS_ENY': 'EPS_est',
    'EPSG_ENY': 'EPS_G%',
    'PE_ENY': 'PE_fwd',
    'P2S_ENY': 'P2S_est',
    'MarketCap': 'MarketCap',
    'Beta': 'Beta'
}
# Rename only the columns that actually exist in the CSV
top_75 = top_75.rename(columns=rename_map)

# 3. Select only the columns needed for "Example 1" style
cols_to_keep = ['EPS_ttm', 'PE_ttm', 'PE_fwd', 'EPS_G%', 'Rev_est', 'Rev_G%', 'MarketCap', 'Beta']
# Ensure we only select columns that exist to avoid errors
df_clean = top_75[[c for c in cols_to_keep if c in top_75.columns]].copy()

# 4. Define formatting functions
def format_currency_short(n):
    try:
        n = float(n)
        if n >= 1e12: return f"${n/1e12:.2f}T"
        if n >= 1e9:  return f"${n/1e9:.2f}B"
        if n >= 1e6:  return f"${n/1e6:.2f}M"
        return f"${n:,.0f}"
    except:
        return n

def format_pct(x):
    try:
        # Assuming your raw data is a decimal (e.g., 0.05 for 5%)
        # If your data is already 5.0, remove the "* 100"
        return f"{float(x) * 100:.1f}%"
    except:
        return x

# 5. Apply formatting to the copy
if 'Rev_est' in df_clean.columns:
    df_clean['Rev_est'] = df_clean['Rev_est'].apply(format_currency_short)

if 'MarketCap' in df_clean.columns:
    df_clean['MarketCap'] = df_clean['MarketCap'].apply(format_currency_short)

if 'Rev_G%' in df_clean.columns:
    df_clean['Rev_G%'] = df_clean['Rev_G%'].apply(format_pct)

if 'EPS_G%' in df_clean.columns:
    df_clean['EPS_G%'] = df_clean['EPS_G%'].apply(format_pct)

# Round the remaining numeric columns to 2 decimal places
numeric_cols = ['EPS_ttm', 'PE_ttm', 'PE_fwd', 'Beta']
for col in numeric_cols:
    if col in df_clean.columns:
        df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').round(2)

# 6. Final Output
df_clean.index.name = None
print('\n')
print(df_clean)
print('\n')