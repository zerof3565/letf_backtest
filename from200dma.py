import csv
import logging
import os
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


BASE_DIR = os.path.join(os.getcwd(), "yquery")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "period_returns.csv")
OLD_RESULT_FILES = [
    RESULTS_FILE,
    os.path.join(RESULTS_DIR, "period_returns_0.csv"),
    os.path.join(RESULTS_DIR, "period_returns_1.csv"),
    os.path.join(RESULTS_DIR, "failed_symbols.csv"),
]
OUTPUT_WINDOW = 252


warnings.simplefilter(action="ignore", category=FutureWarning)


def cleanup_old_files():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    for file_path in OLD_RESULT_FILES:
        if os.path.exists(file_path):
            os.remove(file_path)


def parse_symbol():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python yquery/from200dma.py SYMBOL")

    symbol = sys.argv[1].strip().upper()
    if not symbol:
        raise SystemExit("A ticker symbol is required.")

    if symbol.endswith(".csv") or "," in symbol:
        raise SystemExit("from200dma.py accepts exactly one ticker symbol at a time.")

    return symbol


def flatten_download(downloaded, symbol):
    if downloaded.empty:
        return pd.DataFrame()

    if isinstance(downloaded.columns, pd.MultiIndex):
        if symbol in downloaded.columns.get_level_values(0):
            frame = downloaded[symbol].copy()
        elif symbol in downloaded.columns.get_level_values(-1):
            frame = downloaded.xs(symbol, axis=1, level=-1).copy()
        else:
            frame = downloaded.copy()
            frame.columns = frame.columns.get_level_values(0)
    else:
        frame = downloaded.copy()

    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]

    if "dividends" not in frame.columns:
        frame["dividends"] = 0.0

    for column in ["open", "high", "low", "close", "volume", "dividends"]:
        if column not in frame.columns:
            frame[column] = 0.0 if column in {"volume", "dividends"} else np.nan

    return frame


def normalize_index(index, timezone_name=None):
    normalized = pd.DatetimeIndex(pd.to_datetime(index))
    if normalized.tz is not None:
        if timezone_name:
            normalized = normalized.tz_convert(timezone_name)
        normalized = normalized.tz_localize(None)
    return normalized


def get_exchange_timezone(symbol):
    try:
        timezone_name = yf.Ticker(symbol).fast_info.get("timezone")
        if timezone_name:
            return timezone_name
    except Exception as exc:
        logger.debug("Could not determine exchange timezone for %s: %s", symbol, exc)
    return None


def fetch_daily_history(symbol):
    downloaded = yf.download(
        symbol,
        period="max",
        interval="1d",
        progress=False,
        auto_adjust=False,
        actions=True,
        group_by="ticker",
        threads=False,
    )
    history = flatten_download(downloaded, symbol)
    if history.empty:
        return history

    history.index = normalize_index(history.index).normalize()
    history = history[~history.index.duplicated(keep="last")].sort_index()
    return history


def fetch_intraday_session(symbol, timezone_name):
    downloaded = yf.download(
        symbol,
        period="1d",
        interval="1m",
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        prepost=False,
        threads=False,
    )
    intraday = flatten_download(downloaded, symbol)
    if intraday.empty or intraday["close"].dropna().empty:
        return None, None

    intraday.index = normalize_index(intraday.index, timezone_name)
    intraday = intraday.sort_index()

    session_date = intraday.index[-1].normalize()
    session_frame = intraday.loc[intraday.index.normalize() == session_date]
    if session_frame.empty:
        return None, None

    session_row = {
        "open": session_frame["open"].dropna().iloc[0],
        "high": session_frame["high"].max(),
        "low": session_frame["low"].min(),
        "close": session_frame["close"].dropna().iloc[-1],
        "volume": float(session_frame["volume"].fillna(0).sum()),
    }
    return session_date, session_row


def merge_live_session(history, symbol):
    timezone_name = get_exchange_timezone(symbol)

    try:
        session_date, session_row = fetch_intraday_session(symbol, timezone_name)
    except Exception as exc:
        logger.warning("Could not refresh live session data for %s: %s", symbol, exc)
        return history

    if session_date is None or session_row is None:
        return history

    dividends = 0.0
    if session_date in history.index and pd.notna(history.at[session_date, "dividends"]):
        dividends = float(history.at[session_date, "dividends"])

    for column, value in session_row.items():
        history.loc[session_date, column] = value

    history.loc[session_date, "dividends"] = dividends
    history = history.sort_index()
    # logger.info("Applied intraday session data for %s on %s", symbol, session_date.date())
    return history


def build_output_frame(history):
    frame = history.copy().iloc[-OUTPUT_WINDOW:]
    frame["200DMA"] = frame["close"].rolling(window=200).mean()
    frame["pct_from_200DMA"] = (frame["close"] - frame["200DMA"]) / frame["200DMA"] * 100

    dividend_mask = frame["dividends"].fillna(0) != 0
    previous_qtr_close = frame.loc[dividend_mask, "close"].tolist()

    qtr_returns = np.nan
    if len(previous_qtr_close) >= 2:
        qtr_returns = (previous_qtr_close[-1] - previous_qtr_close[-2]) / previous_qtr_close[-2] * 100

    frame["Qtr_Returns"] = np.nan
    if pd.notna(qtr_returns):
        frame.loc[dividend_mask, "Qtr_Returns"] = qtr_returns

    frame.loc[~dividend_mask, "dividends"] = np.nan

    for column in ["200DMA", "pct_from_200DMA", "open", "high", "low", "close", "Qtr_Returns"]:
        if column in frame.columns:
            frame[column] = frame[column].round(2)

    frame.index = frame.index.date
    frame.index.name = "Date"
    return frame[["200DMA", "pct_from_200DMA", "Qtr_Returns", "dividends"]]


def main():
    cleanup_old_files()
    symbol = parse_symbol()

    history = fetch_daily_history(symbol)
    if history.empty:
        raise SystemExit(f"Could not retrieve price history for {symbol}.")

    history = merge_live_session(history, symbol)
    output = build_output_frame(history)

    with open(RESULTS_FILE, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["Date", "200DMA", "pct_from_200DMA", "Qtr_Returns", "dividends"])

    output.to_csv(RESULTS_FILE, mode="a", header=False)
    console_output = output.tail(21).reset_index()
    print(console_output.to_string(index=False))


if __name__ == "__main__":
    main()
