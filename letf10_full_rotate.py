"""200-SMA rotation backtest with full-rotate take-profit."""

from backtest.engine import build_cli, parse_cli, run_backtest, BacktestConfig

if __name__ == "__main__":
    parser = build_cli("200-SMA rotation backtest — full rotate to safe at +10%")
    cfg = parse_cli(parser.parse_args())
    cfg.half_weights = (0.0, 1.0, 0.0)
    run_backtest(cfg)
