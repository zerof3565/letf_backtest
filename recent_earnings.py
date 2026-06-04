import sys
import numpy as np
import pandas as pd
import warnings
import os
import yfinance as yf




# Supress warnings regarding slicing/copying from master df
warnings.simplefilter(action='ignore', category=FutureWarning)




def parse_number(value):
    if value is None or isinstance(value, dict):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None




def require_number(value, label):
    value = parse_number(value)
    if value is None:
        raise RuntimeError(f'Missing {label}')
    return value




def format_date(value):
    if value is None:
        return 'unknown'
    try:
        if pd.isna(value):
            return 'unknown'
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return str(value).split()[0]




def normalize_statement(statement, required_rows=None):
    if statement is None or statement.empty:
        raise RuntimeError('Yahoo Finance returned an empty financial statement')

    statement = statement.copy()
    statement = statement.sort_index(axis=1, ascending=False)
    if required_rows:
        complete_columns = pd.Series(True, index=statement.columns)
        for row in required_rows:
            if row in statement.index:
                complete_columns &= statement.loc[row].notna()
        statement = statement.loc[:, complete_columns]

    if statement.empty:
        raise RuntimeError('Yahoo Finance returned no complete financial statement periods')

    as_of_dates = [format_date(column) for column in statement.columns]
    statement.columns = range(len(statement.columns))
    statement.loc['asOfDate'] = as_of_dates
    return statement




def get_stock_info(stock):
    try:
        return stock.get_info()
    except Exception:
        return {}




def get_fast_info_value(stock, key):
    try:
        return stock.fast_info.get(key)
    except Exception:
        try:
            return stock.fast_info[key]
        except Exception:
            return None




def get_market_price(stock, stock_info):
    for key in ('regularMarketPrice', 'currentPrice', 'previousClose'):
        price = parse_number(stock_info.get(key))
        if price is not None:
            return price

    for key in ('last_price', 'regular_market_price', 'previous_close'):
        price = parse_number(get_fast_info_value(stock, key))
        if price is not None:
            return price

    return None




def get_shares_outstanding(stock_quarterly_balancesheet, stock_info):
    shares_outstanding = parse_number(stock_info.get('sharesOutstanding'))
    if shares_outstanding is not None:
        return shares_outstanding
    return int(stock_quarterly_balancesheet.loc['OrdinarySharesNumber'][0])




def get_calendar_date(calendar, yfinance_key, stock_info, info_key):
    value = calendar.get(yfinance_key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None

    if value is None:
        value = stock_info.get(info_key)
        if parse_number(value) is not None:
            value = pd.to_datetime(value, unit='s')

    return format_date(value)




def get_estimate(estimate_table, period, column):
    if estimate_table is None or estimate_table.empty:
        return None
    try:
        return parse_number(estimate_table.loc[period, column])
    except Exception:
        return None




def estimate_period_end(stock_quarterly_incomestmt, quarters_ahead, earnings_estimates=None, revenue_estimates=None, period=None):
    estimate_matches = [
        ('BasicEPS', earnings_estimates, 'yearAgoEps'),
        ('TotalRevenue', revenue_estimates, 'yearAgoRevenue'),
    ]
    for statement_row, estimate_table, estimate_column in estimate_matches:
        year_ago_value = get_estimate(estimate_table, period, estimate_column)
        if year_ago_value is None or statement_row not in stock_quarterly_incomestmt.index:
            continue
        for column in stock_quarterly_incomestmt.columns:
            if column == 'asOfDate':
                continue
            actual_value = parse_number(stock_quarterly_incomestmt.loc[statement_row][column])
            if actual_value is None:
                continue
            if statement_row == 'BasicEPS':
                tolerance = max(abs(year_ago_value) * 0.005, 0.02)
            else:
                tolerance = max(abs(year_ago_value) * 0.001, 1_000_000)
            if abs(actual_value - year_ago_value) <= tolerance:
                return format_date(pd.Timestamp(stock_quarterly_incomestmt.loc['asOfDate'][column]) + pd.DateOffset(years=1))

    latest_statement_date = pd.Timestamp(stock_quarterly_incomestmt.loc['asOfDate'][0])
    return format_date(latest_statement_date + pd.DateOffset(months=3 * quarters_ahead))




def get_next_earnings_datetime(stock, calendar):
    try:
        earnings_dates = stock.get_earnings_dates(limit=12)
        if earnings_dates is not None and not earnings_dates.empty:
            return earnings_dates.index[0]
    except Exception:
        pass

    earnings_date = calendar.get('Earnings Date')
    if isinstance(earnings_date, (list, tuple)):
        earnings_date = earnings_date[0] if earnings_date else None
    return earnings_date




def format_earnings_date_line(earnings_datetime):
    if earnings_datetime is None:
        return 'Earnings Date: unavailable'

    timestamp = pd.Timestamp(earnings_datetime)
    earnings_date = format_date(timestamp)
    if timestamp.hour > 12:
        return f'Earnings Date: {earnings_date}, After Market Close'
    if timestamp.hour > 0:
        return f'Earnings Date: {earnings_date}, Before Market Open'
    return f'Earnings Date: {earnings_date}'




def normalize_history(history):
    history = history.copy()
    history.columns = [str(column).lower() for column in history.columns]
    return history




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




# Calculate Liquidity
def calc_liquidity(stock_quarterly_balancesheet):
    #   cash ratio
    if 'CurrentLiabilities' not in stock_quarterly_balancesheet.index:
        current_liabilities_rows = ['AccountsPayable', 'CurrentAccruedExpenses', 'CurrentDebt', 'OtherCurrentBorrowings', 'PayablesAndAccruedExpenses']
        current_liabilities = 0
        for row in current_liabilities_rows:
            if row in stock_quarterly_balancesheet.index:
                current_liabilities += stock_quarterly_balancesheet.loc[row][0]
        if 'CashCashEquivalentsAndShortTermInvestments' not in stock_quarterly_balancesheet.index:
            cash_ratio = (stock_quarterly_balancesheet.loc['CashAndCashEquivalents'][0] + stock_quarterly_balancesheet.loc['OtherShortTermInvestments'][0]) / current_liabilities
        else:
            cash_ratio = stock_quarterly_balancesheet.loc['CashCashEquivalentsAndShortTermInvestments'][0] / current_liabilities
    else:
        cash_ratio = stock_quarterly_balancesheet.loc['CashCashEquivalentsAndShortTermInvestments'][0] / stock_quarterly_balancesheet.loc['CurrentLiabilities'][0]

    #   quick ratio
    if 'CurrentLiabilities' not in stock_quarterly_balancesheet.index:
        quick_assets_rows = ['CashAndCashEquivalents', 'OtherShortTermInvestments', 'CashFinancial', 'AvailableForSaleSecurities', 'AccountsReceivable']
        quick_assets = 0
        for row in quick_assets_rows:
            if row in stock_quarterly_balancesheet.index:
                quick_assets += stock_quarterly_balancesheet.loc[row][0]
        quick_ratio = quick_assets / current_liabilities
    elif 'Inventory' not in stock_quarterly_balancesheet.index and 'AccountsReceivable' in stock_quarterly_balancesheet.index:
        quick_ratio = (stock_quarterly_balancesheet.loc['CashCashEquivalentsAndShortTermInvestments'][0] + stock_quarterly_balancesheet.loc['AccountsReceivable'][0]) / stock_quarterly_balancesheet.loc['CurrentLiabilities'][0]
    elif 'Inventory' not in stock_quarterly_balancesheet.index and 'AccountsReceivable' not in stock_quarterly_balancesheet.index:
        quick_ratio = stock_quarterly_balancesheet.loc['CashCashEquivalentsAndShortTermInvestments'][0] / stock_quarterly_balancesheet.loc['CurrentLiabilities'][0]
    else:
        quick_ratio = (stock_quarterly_balancesheet.loc['CurrentAssets'][0] - stock_quarterly_balancesheet.loc['Inventory'][0]) / stock_quarterly_balancesheet.loc['CurrentLiabilities'][0]

    #   current ratio
    if 'CurrentAssets' not in stock_quarterly_balancesheet.index:
        current_assets_rows = ['CashAndCashEquivalents', 'OtherShortTermInvestments', 'CashFinancial', 'AvailableForSaleSecurities', 'AccountsReceivable', 'InvestmentsAndAdvances', 'OtherReceivables']
        current_assets = 0
        for row in current_assets_rows:
            if row in stock_quarterly_balancesheet.index:
                current_assets += stock_quarterly_balancesheet.loc[row][0]
        current_ratio = current_assets / current_liabilities
    else:
        current_ratio = stock_quarterly_balancesheet.loc['CurrentAssets'][0] / stock_quarterly_balancesheet.loc['CurrentLiabilities'][0]

    #   return liquidity ratios
    return cash_ratio, quick_ratio, current_ratio




# Calculate Financial Stability
def calc_financial_stability(stock_quarterly_balancesheet, stock_quarterly_incomestmt):
    #   add row to dataframe if needed
    if 'TotalDebt' not in stock_quarterly_balancesheet.index:
        stock_quarterly_balancesheet.loc['TotalDebt'] = [stock_quarterly_balancesheet.loc['TotalLiabilitiesNetMinorityInterest'][0]] + [None]*(len(stock_quarterly_balancesheet.columns)-1)

    #   calculate equity, debt and debit-2-equity ratios
    equity_ratio = stock_quarterly_balancesheet.loc['StockholdersEquity'][0] / stock_quarterly_balancesheet.loc['TotalAssets'][0]
    debt_ratio = stock_quarterly_balancesheet.loc['TotalDebt'][0] / stock_quarterly_balancesheet.loc['TotalAssets'][0]
    if stock_quarterly_balancesheet.loc['StockholdersEquity'][0] <= 0:
        stock_quarterly_balancesheet.loc['StockholdersEquity'][0] = 0.0000000000001
    debt_equity_ratio = stock_quarterly_balancesheet.loc['TotalDebt'][0] / stock_quarterly_balancesheet.loc['StockholdersEquity'][0]

    #   calculate Debt-2-EBITDA
    if 'NormalizedEBITDA' in stock_quarterly_incomestmt.index:
        ebitada_ttm = stock_quarterly_incomestmt.iloc[:, :4].loc['NormalizedEBITDA'].sum(axis=0)
        debt_ebitda_ratio = stock_quarterly_balancesheet.loc['TotalDebt'][0] / ebitada_ttm
    else:
        debt_ebitda_ratio = None

    #   return debt ratios
    return equity_ratio, debt_ratio, debt_equity_ratio, debt_ebitda_ratio




# Calculate Profitability
def calc_profitability(stock, stock_quarterly_balancesheet, stock_quarterly_incomestmt, stock_quarterly_cashflow, symbol):
    #   calculate roa, roe, roic
    net_income_year = stock_quarterly_incomestmt.iloc[:, :4].loc['NetIncome'].sum(axis=0)
    total_rev_year = stock_quarterly_incomestmt.iloc[:, :4].loc['TotalRevenue'].sum(axis=0)
    roa = net_income_year / stock_quarterly_balancesheet.loc['TotalAssets'][0]
    if stock_quarterly_balancesheet.loc['StockholdersEquity'][0] <= 0:
        stock_quarterly_balancesheet.loc['StockholdersEquity'][0] = 0.0000000000001
    roe = net_income_year / stock_quarterly_balancesheet.loc['StockholdersEquity'][0]
    if 'InterestExpense' in stock_quarterly_incomestmt.index:
        stock_quarterly_incomestmt.loc['IEAT'] = stock_quarterly_incomestmt.loc['InterestExpense'] * (1 - stock_quarterly_incomestmt.loc['TaxRateForCalcs'])
        dividends = stock_quarterly_incomestmt.iloc[:, :4].loc['IEAT'].sum(axis=0)
    else:
        dividends = 0
    try:
        roic = (stock_quarterly_incomestmt.iloc[:, :4].loc['NetIncome'].sum(axis=0) - dividends) / stock_quarterly_balancesheet.loc['InvestedCapital'][0]
    except Exception:
        roic = 0

    #   calculate Net Profit Margin
    try:
        net_profit_margin_quarter = stock_quarterly_incomestmt.loc['NetIncome'][0] / stock_quarterly_incomestmt.loc['TotalRevenue'][0]
    except Exception:
        net_profit_margin_quarter = 0
    net_profit_margin_year = net_income_year / total_rev_year

    #   calculate Gross Profit Margin and Operating Profit Margin
    if 'GrossProfit' in stock_quarterly_incomestmt.index:
        gross_income_year = stock_quarterly_incomestmt.iloc[:, :4].loc['GrossProfit'].sum(axis=0)
        op_income_year = stock_quarterly_incomestmt.iloc[:, :4].loc['OperatingIncome'].sum(axis=0)

        #   calculate Gross Profit Margin
        gross_profit_margin_quarter = stock_quarterly_incomestmt.loc['GrossProfit'][0] / stock_quarterly_incomestmt.loc['TotalRevenue'][0]
        gross_profit_margin_year = gross_income_year / total_rev_year

        #   calculate Operating Profit Margin
        op_profit_margin_quarter = stock_quarterly_incomestmt.loc['OperatingIncome'][0] / stock_quarterly_incomestmt.loc['TotalRevenue'][0]
        op_profit_margin_year = op_income_year / total_rev_year

    else:
        gross_profit_margin_quarter = gross_profit_margin_year = op_profit_margin_quarter = op_profit_margin_year = None

    #   return profitability ratios
    return roa, roe, roic, gross_profit_margin_quarter, gross_profit_margin_year, op_profit_margin_quarter, op_profit_margin_year, \
            net_profit_margin_quarter, net_profit_margin_year




# Calculate price ratios
def calc_price_ratios(stock, stock_info, stock_quarterly_balancesheet, stock_quarterly_incomestmt, stock_quarterly_cashflow, symbol):
    current_price = require_number(get_market_price(stock, stock_info), 'current stock price')
    shares_outstanding = get_shares_outstanding(stock_quarterly_balancesheet, stock_info)
    #   Price-2-Sales
    price_to_sales = current_price / (stock_quarterly_incomestmt.iloc[:, :4].loc['TotalRevenue'].sum(axis=0) / shares_outstanding)
    #   Price-2-GrossIncome
    try:
        price_to_grossincome = current_price / (stock_quarterly_incomestmt.iloc[:, :4].loc['GrossProfit'].sum(axis=0) / shares_outstanding)
    except Exception:
        price_to_grossincome = None
    #   Price-2-Book
    if stock_quarterly_balancesheet.loc['StockholdersEquity'][0] != 0:
        price_to_book = current_price / (stock_quarterly_balancesheet.loc['StockholdersEquity'][0] / shares_outstanding)
    else:
        price_to_book = 0
    #   EPS
    try:
        earnings_per_share = stock_quarterly_incomestmt.iloc[:, :4].loc['BasicEPS'].sum(axis=0)
    except Exception:
        earnings_per_share = stock_quarterly_incomestmt.iloc[:, :4].loc['NetIncome'].sum(axis=0) / shares_outstanding
    #   P/E
    price_per_earnings = current_price / earnings_per_share
    #   Price-2-FCF
    price_to_fcf = current_price / (stock_quarterly_cashflow.iloc[:, :4].loc['FreeCashFlow'].sum() / shares_outstanding)
    #   FCF-2-Equity
    if stock_quarterly_balancesheet.loc['StockholdersEquity'][0] != 0:
        fcf_to_equity = stock_quarterly_cashflow.iloc[:, :4].loc['FreeCashFlow'].sum() / stock_quarterly_balancesheet.loc['StockholdersEquity'][0]
    else:
        fcf_to_equity = 0
    #   FCF-2-Share
    fcf_to_share = stock_quarterly_cashflow.iloc[:, :4].loc['FreeCashFlow'].sum() / shares_outstanding

    #   return price ratios
    return price_to_sales, price_to_grossincome, price_to_book, earnings_per_share, price_per_earnings, price_to_fcf, fcf_to_equity, fcf_to_share




# Get yield
def get_yield(stock, stock_info, symbol):
    stock_yield_ttm = parse_number(stock_info.get('trailingAnnualDividendYield'))
    if stock_yield_ttm is None:
        dividend_rate = parse_number(stock_info.get('dividendRate') or stock_info.get('trailingAnnualDividendRate'))
        current_price = parse_number(get_market_price(stock, stock_info))
        if dividend_rate is not None and current_price:
            stock_yield_ttm = dividend_rate / current_price

    if stock_yield_ttm is None:
        stock_yield_ttm = parse_number(stock_info.get('dividendYield')) or 0
        if stock_yield_ttm > 0.15:
            stock_yield_ttm = stock_yield_ttm / 100

    stock_yield = round((float(stock_yield_ttm)*100),2)
    return stock_yield




def main():
    #   Setup symbols and fetch Yahoo Finance data
    stock = yf.Ticker(symbol)
    market = yf.Ticker('^SP500TR')
    stock_info = get_stock_info(stock)

    #   get yahoo data for the 3 financial statements
    stock_quarterly_balancesheet = normalize_statement(
        stock.get_balance_sheet(freq='quarterly', pretty=False),
        required_rows=['TotalAssets', 'StockholdersEquity'],
    )
    stock_quarterly_incomestmt = normalize_statement(
        stock.get_income_stmt(freq='quarterly', pretty=False),
        required_rows=['TotalRevenue', 'NetIncome'],
    )
    stock_quarterly_cashflow = normalize_statement(
        stock.get_cashflow(freq='quarterly', pretty=False),
        required_rows=['FreeCashFlow'],
    )

    #   Get history for beta calculation
    stock_history = normalize_history(stock.history(period='3y', interval='1d', auto_adjust=False))
    market_history = normalize_history(market.history(period='3y', interval='1d', auto_adjust=False))

    # Output financial sttements to csv for manual checking
    output_dir = os.path.join(os.getcwd(), 'yquery', 'yfinance')
    os.makedirs(output_dir, exist_ok=True)
    stock_quarterly_cashflow.to_csv(os.path.join(output_dir, f'{symbol}_cashflow.csv'))
    stock_quarterly_balancesheet.to_csv(os.path.join(output_dir, f'{symbol}_balancesheet.csv'))
    stock_quarterly_incomestmt.to_csv(os.path.join(output_dir, f'{symbol}_incomestmt.csv'))

    #   calculate liquidity ratios
    cash_ratio, quick_ratio, current_ratio = calc_liquidity(stock_quarterly_balancesheet)
    print(f'\n{symbol} - {stock_quarterly_balancesheet.loc["asOfDate"][0]}')
    label = 'LIQUIDITY'
    print(f'{"-" * len(label)}')
    print(f'{label}')
    print(f'Cash Ratio: {round(cash_ratio, 2)}')
    print(f'Quick Ratio: {round(quick_ratio, 2)}')
    print(f'Current Ratio: {round(current_ratio, 2)}')

    #   calculate financial stability ratios
    equity_ratio, debt_ratio, debt_equity_ratio, debt_ebitda_ratio = calc_financial_stability(stock_quarterly_balancesheet, stock_quarterly_incomestmt)
    label = 'FINANCIAL STABILITY'
    print(f'{"-" * len(label)}')
    print(f'{label}')
    print(f'Equity Ratio: {round(equity_ratio, 2)}')
    print(f'Debt Ratio: {round(debt_ratio, 2)}')
    print(f'Debt-2-Equity: {round(debt_equity_ratio, 2)}')
    if debt_ebitda_ratio:
        print(f'Debt-2-EBITDA: {round(debt_ebitda_ratio, 2)}')

    #   calculate profitability
    roa, roe, roic, gross_profit_margin_quarter, gross_profit_margin_year, op_profit_margin_quarter, op_profit_margin_year, \
        net_profit_margin_quarter, net_profit_margin_year = calc_profitability(stock, stock_quarterly_balancesheet, stock_quarterly_incomestmt, stock_quarterly_cashflow, symbol)
    label = 'PROFITABILITY'
    print(f'{"-" * len(label)}')
    print(f'{label}')
    print(f'Return on Assets: {round(roa*100, 2)}%')
    print(f'Return on Equity: {round(roe*100, 2)}%')
    print(f'Return on Invested Capital: {round(roic*100, 2)}%')
    if gross_profit_margin_quarter:
        print(f'Gross Margin (Quarter): {round(gross_profit_margin_quarter*100, 2)}%')
        print(f'Gross Margin (Year): {round(gross_profit_margin_year*100, 2)}%')
        print(f'Operating Margin (Quarter): {round(op_profit_margin_quarter*100, 2)}%')
        print(f'Operating Margin (Year): {round(op_profit_margin_year*100, 2)}%')
    print(f'Net Margin (Quarter): {round(net_profit_margin_quarter*100, 2)}%')
    print(f'Net Margin (Year): {round(net_profit_margin_year*100, 2)}%')

    #   calculte price ratios
    price_to_sales, price_to_grossincome, price_to_book, earnings_per_share, price_per_earnings, price_to_fcf, \
        fcf_to_equity, fcf_to_share = calc_price_ratios(stock, stock_info, stock_quarterly_balancesheet, stock_quarterly_incomestmt, stock_quarterly_cashflow, symbol)
        #   output price ratios
    label = 'PRICE RATIOS'
    print(f'{"-" * len(label)}')
    print(f'{label}')
    print(f'Price-2-Sales: {round(price_to_sales, 2)}')
    if price_to_grossincome is not None:
        print(f'Price-2-GrossProfit: {round(price_to_grossincome, 2)}')
    print(f'Price-2-Book: {round(price_to_book, 2)}')
    print(f'EPS: {round(earnings_per_share, 2)}')
    print(f'P/E: {round(price_per_earnings, 2)}')
    print(f'FCF-2-Share: {round(fcf_to_share, 2)}')
    print(f'Price-2-FCF: {round(price_to_fcf, 2)}')
    print(f'FCF-2-Equity: {round(fcf_to_equity, 2)}')

    #   other metrics
    label = 'OTHER METRICS'
    print(f'{"-" * len(label)}')
    print(f'{label}')
        #   calculate beta
    try:
        beta = calc_beta(stock_history, market_history)
    except Exception:
        beta = 0
    print(f'Beta (3Y Daily): {round(beta, 2)}')

    #   dividends info
    calendar = stock.calendar or {}
    stock_yield = get_yield(stock, stock_info, symbol)
    print(f'Current Yield: {stock_yield}%')
    if stock_yield == 0:
        print('No dividends info')
    else:
        print(f"exDividend Date: {get_calendar_date(calendar, 'Ex-Dividend Date', stock_info, 'exDividendDate')}, After 4PM EST")
        print(f"Dividend Payment Date: {get_calendar_date(calendar, 'Dividend Date', stock_info, 'dividendDate')}, After 5PM EST")

    # earnings report info
    label = 'EARNINGS INFO'
    print(f'{"-" * len(label)}')
    print(f'{label}')
        # current quarter
    try:
        earnings_estimates = stock.get_earnings_estimate()
        revenue_estimates = stock.get_revenue_estimate()
        current_price = require_number(get_market_price(stock, stock_info), 'current stock price')
        outstanding_shares = get_shares_outstanding(stock_quarterly_balancesheet, stock_info)

        print(f'Current Quarter End Date: {estimate_period_end(stock_quarterly_incomestmt, 1, earnings_estimates, revenue_estimates, "0q")}')
        print(format_earnings_date_line(get_next_earnings_datetime(stock, calendar)))
            # revenue estimate
        rev_estimate_q = require_number(get_estimate(revenue_estimates, '0q', 'avg') or calendar.get('Revenue Average'), 'current quarter revenue estimate')
        rev_growth_q = require_number(get_estimate(revenue_estimates, '0q', 'growth'), 'current quarter revenue growth estimate') * 100
        rev_estimate_y = stock_quarterly_incomestmt.iloc[:, :3].loc['TotalRevenue'].sum(axis=0) + rev_estimate_q
                # price to sales estimate
        price_to_sales_estimate = current_price / (rev_estimate_y / outstanding_shares)
        print(f"Revenue Estimate (quarterly): ${rev_estimate_q:,.0f}")
        print(f"Revenue Growth Estimate (quarterly): {rev_growth_q:.2f}%")
        print(f"Revenue Estimate (ttm): ${rev_estimate_y:,.0f}")
        print(f"Price-2-Sales Estimate at Current Stock Price: {price_to_sales_estimate:.2f}")
            # eps estimate
        eps_estimate_q = require_number(get_estimate(earnings_estimates, '0q', 'avg') or calendar.get('Earnings Average'), 'current quarter EPS estimate')
        eps_growth_q = require_number(get_estimate(earnings_estimates, '0q', 'growth'), 'current quarter EPS growth estimate') * 100
        eps_estimate_y = stock_quarterly_incomestmt.iloc[:, :3].loc['BasicEPS'].sum(axis=0) + eps_estimate_q
        print(f"EPS Estimate (quarterly): {eps_estimate_q}")
        print(f"EPS Growth Estimate (quarterly): {eps_growth_q:.2f}%")
        print(f"EPS Estimate (ttm): {eps_estimate_y:.2f}")
        print(f"P/E Estimate at Current Stock Price: {current_price / eps_estimate_y:.2f}")
        print(f"No. of Analysts: {get_estimate(earnings_estimates, '0q', 'numberOfAnalysts'):.0f}")
        # next quarter
            # revenue estimate
        rev_estimate_nq = require_number(get_estimate(revenue_estimates, '+1q', 'avg'), 'next quarter revenue estimate')
        rev_growth_nq = require_number(get_estimate(revenue_estimates, '+1q', 'growth'), 'next quarter revenue growth estimate') * 100
        rev_estimate_nqy = stock_quarterly_incomestmt.iloc[:, :2].loc['TotalRevenue'].sum(axis=0) + rev_estimate_q + rev_estimate_nq
        price_to_sales_estimate_nq = current_price / (rev_estimate_nqy / outstanding_shares)
        line2 = f'Next Quarter End Date: {estimate_period_end(stock_quarterly_incomestmt, 2, earnings_estimates, revenue_estimates, "+1q")}'
        print('-' * len(line2))
        print(line2)
        print(f"Revenue Estimate (quarterly): ${rev_estimate_nq:,.0f}")
        print(f"Revenue Growth Estimate (quarterly): {rev_growth_nq:.2f}%")
        print(f"Revenue Estimate (ttm): ${rev_estimate_nqy:,.0f}")
        print(f"Price-2-Sales Estimate at Current Stock Price: {price_to_sales_estimate_nq:.2f}")
            # eps estimate
        eps_estimate_nq = require_number(get_estimate(earnings_estimates, '+1q', 'avg'), 'next quarter EPS estimate')
        eps_growth_nq = require_number(get_estimate(earnings_estimates, '+1q', 'growth'), 'next quarter EPS growth estimate') * 100
        eps_estimate_nqy = stock_quarterly_incomestmt.iloc[:, :2].loc['BasicEPS'].sum(axis=0) + eps_estimate_q + eps_estimate_nq
        print(f"EPS Estimate (quarterly): {eps_estimate_nq}")
        print(f"EPS Growth Estimate (quarterly): {eps_growth_nq:.2f}%")
        print(f"EPS Estimate (ttm): {eps_estimate_nqy:.2f}")
        print(f"P/E Estimate at Current Stock Price: {current_price / eps_estimate_nqy:.2f}")
        # next year
        rev_estimate_next_year = require_number(get_estimate(revenue_estimates, '+1y', 'avg'), 'next year revenue estimate')
        rev_growth_next_year = require_number(get_estimate(revenue_estimates, '+1y', 'growth'), 'next year revenue growth estimate')
        eps_estimate_next_year = require_number(get_estimate(earnings_estimates, '+1y', 'avg'), 'next year EPS estimate')
        eps_growth_next_year = require_number(get_estimate(earnings_estimates, '+1y', 'growth'), 'next year EPS growth estimate')
        price_to_sales_estimate_next_year = current_price / (rev_estimate_next_year / outstanding_shares)
        label = "Next Year Estimates"
        print(f'{"-" * len(label)}')
        print(f'{label}')
        print(f"Revenue Estimate (yearly): ${rev_estimate_next_year:,.0f}")
        print(f"Revenue Growth Estimate (yearly): {rev_growth_next_year*100:.2f}%")
        print(f"Price-2-Sales Estimate at Current Stock Price: {price_to_sales_estimate_next_year:.2f}")
        print(f"EPS Growth Estimate (yearly): {eps_growth_next_year*100:.2f}%")
        print(f"EPS Estimate (yearly): {eps_estimate_next_year}")
        print(f"P/E Estimate at Current Stock Price: {current_price / eps_estimate_next_year:.2f}")
    except Exception as exc:
        print(f'Earnings estimates unavailable: {exc}')




if __name__ == '__main__':
    # Get user's input
    symbol = sys.argv[1].upper()

    # Execute main process
    sys.exit(main())
