import argparse
import math
import re
import sys
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path

import pandas as pd
import yfinance as yf


USER_AGENT = "Mozilla/5.0 (compatible; etf-pe/1.0)"


@dataclass
class Holding:
    symbol: str
    name: str
    weight: float
    shares: int | None = None


def parse_number(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("$", "").strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def parse_weight(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "").replace(",", "")
        number = parse_number(cleaned)
        if number is None:
            return None
        return number / 100
    number = parse_number(value)
    if number is None:
        return None
    return number / 100


def fetch_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_stockanalysis_holdings(etf_symbol):
    url = f"https://stockanalysis.com/etf/{etf_symbol.lower()}/holdings/"
    html = fetch_url(url)

    holdings_match = re.search(r"holdings:\[(.*?)\],asset_allocation", html, re.S)
    if not holdings_match:
        raise RuntimeError(f"Could not find holdings data in {url}")

    holding_pattern = re.compile(
        r"\{no:(?P<no>\d+),"
        r'n:"(?P<name>(?:\\"|[^"])*)",'
        r's:"\$?(?P<symbol>[^"]+)",'
        r'as:"(?P<weight>[\d.]+)%",'
        r'sh:"(?P<shares>[\d,]+)"\}'
    )

    holdings = []
    for match in holding_pattern.finditer(holdings_match.group(1)):
        symbol = match.group("symbol").replace(".", "-").upper()
        weight = parse_weight(match.group("weight"))
        shares = parse_number(match.group("shares"))
        if not symbol or weight is None:
            continue
        holdings.append(
            Holding(
                symbol=symbol,
                name=unescape(match.group("name").replace(r"\"", '"')),
                weight=weight,
                shares=int(shares) if shares is not None else None,
            )
        )

    if not holdings:
        raise RuntimeError(f"Found the holdings block in {url}, but parsed zero holdings")

    date_match = re.search(r'date:"([^"]+)"', html)
    pe_match = re.search(r"peRatio:([0-9.]+)", html)
    metadata = {
        "source": url,
        "holdings_date": date_match.group(1) if date_match else None,
        "source_pe": parse_number(pe_match.group(1)) if pe_match else None,
    }
    return holdings, metadata


def load_holdings_csv(path):
    df = pd.read_csv(path)
    column_lookup = {column.lower().strip(): column for column in df.columns}

    symbol_column = (
        column_lookup.get("symbol")
        or column_lookup.get("ticker")
        or column_lookup.get("holding ticker")
    )
    weight_column = (
        column_lookup.get("weight")
        or column_lookup.get("% weight")
        or column_lookup.get("% of net assets")
        or column_lookup.get("percentage")
        or column_lookup.get("as")
    )
    name_column = (
        column_lookup.get("name")
        or column_lookup.get("holding name")
        or column_lookup.get("company")
    )

    if not symbol_column or not weight_column:
        raise ValueError(
            "CSV must include symbol/ticker and weight columns. "
            "Accepted names include Symbol, Ticker, Weight, and % of Net Assets."
        )

    holdings = []
    for _, row in df.iterrows():
        symbol = str(row[symbol_column]).strip().replace(".", "-").upper()
        weight = parse_weight(row[weight_column])
        if not symbol or symbol.lower() == "nan" or weight is None:
            continue
        name = str(row[name_column]).strip() if name_column else symbol
        holdings.append(Holding(symbol=symbol, name=name, weight=weight))

    if not holdings:
        raise ValueError(f"Parsed zero holdings from {path}")

    return holdings, {"source": str(path), "holdings_date": None, "source_pe": None}


def get_stock_metrics(symbol, method):
    ticker = yf.Ticker(symbol)
    info = ticker.info

    if method == "forward":
        eps = parse_number(info.get("forwardEps"))
        pe = parse_number(info.get("forwardPE"))
    else:
        eps = parse_number(info.get("trailingEps"))
        pe = parse_number(info.get("trailingPE"))

    price = (
        parse_number(info.get("regularMarketPrice"))
        or parse_number(info.get("currentPrice"))
        or parse_number(info.get("previousClose"))
    )

    if price is None:
        try:
            price = parse_number(ticker.fast_info.get("last_price"))
        except Exception:
            price = None

    if price and eps is not None and eps != 0:
        earnings_yield = eps / price
        pe = price / eps
    elif pe is not None and pe != 0:
        earnings_yield = 1 / pe
    else:
        earnings_yield = None

    return {
        "price": price,
        "eps": eps,
        "pe": pe,
        "earnings_yield": earnings_yield,
    }


def calculate_portfolio_pe(
    holdings,
    method,
    positive_only=False,
    cap_pe=None,
    renormalize=False,
):
    rows = []
    included_weight = 0.0
    earnings_yield_sum = 0.0

    for holding in holdings:
        error = None
        metrics = {"price": None, "eps": None, "pe": None, "earnings_yield": None}

        try:
            metrics = get_stock_metrics(holding.symbol, method)
        except Exception as exc:
            error = str(exc)

        earnings_yield = metrics["earnings_yield"]
        include = earnings_yield is not None
        reason = ""

        if not include:
            reason = error or "missing EPS/PE data"
        elif positive_only and earnings_yield <= 0:
            include = False
            reason = "non-positive earnings"
        elif cap_pe and metrics["pe"] and metrics["pe"] > cap_pe:
            earnings_yield = 1 / cap_pe
            metrics["pe"] = cap_pe
            reason = f"P/E capped at {cap_pe:g}"

        if include:
            included_weight += holding.weight
            earnings_yield_sum += holding.weight * earnings_yield

        rows.append(
            {
                "symbol": holding.symbol,
                "name": holding.name,
                "weight": holding.weight,
                "price": metrics["price"],
                "eps": metrics["eps"],
                "pe": metrics["pe"],
                "earnings_yield": earnings_yield,
                "included": include,
                "note": reason,
            }
        )

    if renormalize and included_weight > 0:
        earnings_yield_sum = earnings_yield_sum / included_weight

    portfolio_pe = None
    if earnings_yield_sum > 0:
        portfolio_pe = 1 / earnings_yield_sum

    return portfolio_pe, included_weight, pd.DataFrame(rows)


def format_percent(value):
    return "N/A" if value is None else f"{value:.2%}"


def print_results(etf_symbol, method, portfolio_pe, included_weight, holdings, metadata, rows, args):
    total_weight = sum(holding.weight for holding in holdings)
    print(f"\n{etf_symbol.upper()} look-through P/E ({method.upper()}):")
    print(f"  Calculated P/E: {portfolio_pe:.2f}" if portfolio_pe else "  Calculated P/E: N/A")
    print(f"  Holdings source: {metadata['source']}")
    if metadata.get("holdings_date"):
        print(f"  Holdings date: {metadata['holdings_date']}")
    if metadata.get("source_pe") is not None:
        print(f"  Source displayed P/E: {metadata['source_pe']:.2f}")
    print(f"  Holdings parsed: {len(holdings)}")
    print(f"  Total parsed weight: {format_percent(total_weight)}")
    print(f"  Included weight: {format_percent(included_weight)}")
    print(f"  Renormalized included holdings: {'yes' if args.renormalize else 'no'}")
    print(f"  Positive earnings only: {'yes' if args.positive_only else 'no'}")
    if args.cap_pe:
        print(f"  P/E cap: {args.cap_pe:g}")

    display = rows.copy()
    display["weight"] = display["weight"].map(lambda value: f"{value:.2%}")
    for column in ["price", "eps", "pe", "earnings_yield"]:
        display[column] = display[column].map(
            lambda value: "" if pd.isna(value) else f"{float(value):.4f}"
        )

    columns = ["symbol", "weight", "price", "eps", "pe", "earnings_yield", "included", "note"]
    print("\n" + display[columns].head(args.top).to_string(index=False))

    excluded = rows[~rows["included"]]
    if not excluded.empty:
        print("\nExcluded holdings:")
        print(excluded[["symbol", "weight", "note"]].to_string(index=False))


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Calculate an ETF look-through P/E from holding weights and Yahoo Finance "
            "stock EPS/price data."
        )
    )
    parser.add_argument("etf", nargs="?", default="SMH", help="ETF ticker. Default: SMH")
    parser.add_argument(
        "--method",
        choices=["ttm", "forward"],
        default="ttm",
        help="Use trailing twelve month EPS or forward EPS. Default: ttm",
    )
    parser.add_argument(
        "--holdings-csv",
        type=Path,
        help="Optional holdings CSV with Symbol/Ticker and Weight/%% of Net Assets columns.",
    )
    parser.add_argument(
        "--positive-only",
        action="store_true",
        help="Exclude holdings with non-positive earnings yields.",
    )
    parser.add_argument(
        "--cap-pe",
        type=float,
        help="Cap positive holding P/E values before aggregating, e.g. --cap-pe 60.",
    )
    parser.add_argument(
        "--renormalize",
        action="store_true",
        help="Reweight included holdings to 100%% after missing/excluded holdings are removed.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Number of holding rows to print. Default: 30",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Write holding-level calculation details to this CSV file.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])

    if args.holdings_csv:
        holdings, metadata = load_holdings_csv(args.holdings_csv)
    else:
        holdings, metadata = fetch_stockanalysis_holdings(args.etf)

    portfolio_pe, included_weight, rows = calculate_portfolio_pe(
        holdings=holdings,
        method=args.method,
        positive_only=args.positive_only,
        cap_pe=args.cap_pe,
        renormalize=args.renormalize,
    )

    print_results(
        etf_symbol=args.etf,
        method=args.method,
        portfolio_pe=portfolio_pe,
        included_weight=included_weight,
        holdings=holdings,
        metadata=metadata,
        rows=rows,
        args=args,
    )

    if args.output_csv:
        rows.to_csv(args.output_csv, index=False)
        print(f"\nWrote details to {args.output_csv}")


if __name__ == "__main__":
    main()
