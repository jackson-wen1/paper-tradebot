"""Tests for the backtesting engine and strategy signal generation."""

import numpy as np
import pandas as pd
import pytest

from infrastructure.backtesting import BacktestEngine, BacktestConfig, BacktestResult, format_backtest_report


def _make_ohlcv(n: int = 100, start_price: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
    prices = [start_price]
    for _ in range(n - 1):
        change = rng.normal(0, 0.02) * prices[-1]
        prices.append(max(prices[-1] + change, 1.0))

    close = np.array(prices)
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    open_ = close * (1 + rng.uniform(-0.01, 0.01, n))
    volume = rng.integers(100_000, 1_000_000, n)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


def _make_alternating_signals(data: pd.DataFrame) -> pd.DataFrame:
    """Buy on first bar, sell on 10th, buy on 20th, etc."""
    signal = pd.Series(0, index=data.index)
    for i in range(0, len(data), 20):
        if i < len(data):
            signal.iloc[i] = 1
        if i + 10 < len(data):
            signal.iloc[i + 10] = -1
    return pd.DataFrame({"signal": signal}, index=data.index)


class TestBacktestEngine:
    def test_basic_run(self) -> None:
        data = _make_ohlcv(100)
        signals = _make_alternating_signals(data)
        engine = BacktestEngine(BacktestConfig(initial_capital=100_000))
        result = engine.run(data, signals, "TEST")

        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) == 100
        assert result.metrics["total_trades"] > 0
        assert result.metrics["initial_capital"] == 100_000

    def test_no_signals(self) -> None:
        data = _make_ohlcv(50)
        signals = pd.DataFrame({"signal": [0] * 50}, index=data.index)
        engine = BacktestEngine()
        result = engine.run(data, signals, "TEST")

        assert result.metrics["total_trades"] == 0
        assert result.metrics["final_equity"] == pytest.approx(100_000, abs=0.01)

    def test_all_buy_signals(self) -> None:
        data = _make_ohlcv(20)
        # Buy on first bar only (can't buy if already holding)
        signals = pd.DataFrame({"signal": [1] + [0] * 19}, index=data.index)
        engine = BacktestEngine()
        result = engine.run(data, signals, "TEST")

        # Should have 1 trade (auto-closed at end)
        assert result.metrics["total_trades"] == 1

    def test_metrics_keys(self) -> None:
        data = _make_ohlcv(100)
        signals = _make_alternating_signals(data)
        engine = BacktestEngine()
        result = engine.run(data, signals, "TEST")

        expected_keys = [
            "total_return_pct", "annualized_return_pct", "sharpe_ratio",
            "sortino_ratio", "max_drawdown_pct", "max_drawdown_duration_days",
            "total_trades", "win_rate", "avg_win", "avg_loss",
            "profit_factor", "avg_holding_period_days",
            "initial_capital", "final_equity",
        ]
        for key in expected_keys:
            assert key in result.metrics, f"Missing metric: {key}"

    def test_format_report(self) -> None:
        data = _make_ohlcv(100)
        signals = _make_alternating_signals(data)
        engine = BacktestEngine()
        result = engine.run(data, signals, "TEST")
        report = format_backtest_report(result)

        assert "BACKTEST RESULTS" in report
        assert "Sharpe Ratio" in report
        assert "Win Rate" in report

    def test_slippage_reduces_returns(self) -> None:
        data = _make_ohlcv(100)
        signals = _make_alternating_signals(data)

        no_slip = BacktestEngine(BacktestConfig(slippage_pct=0.0))
        result_no_slip = no_slip.run(data, signals, "TEST")

        with_slip = BacktestEngine(BacktestConfig(slippage_pct=0.01))
        result_with_slip = with_slip.run(data, signals, "TEST")

        # Slippage should reduce final equity
        assert result_with_slip.metrics["final_equity"] <= result_no_slip.metrics["final_equity"]

    def test_signal_column_required(self) -> None:
        data = _make_ohlcv(10)
        bad_signals = pd.DataFrame({"wrong": [0] * 10}, index=data.index)
        engine = BacktestEngine()

        with pytest.raises(ValueError, match="signal"):
            engine.run(data, bad_signals, "TEST")


class TestMomentumSignals:
    def test_generate_signals_shape(self) -> None:
        from strategies.momentum import generate_signals, MomentumConfig

        data = _make_ohlcv(100)
        config = MomentumConfig(min_confirmations=1)
        signals = generate_signals(data, config)

        assert "signal" in signals.columns
        assert "rsi" in signals.columns
        assert "macd" in signals.columns
        assert len(signals) == len(data)

    def test_signals_are_valid(self) -> None:
        from strategies.momentum import generate_signals

        data = _make_ohlcv(200)
        signals = generate_signals(data)

        assert signals["signal"].isin([-1, 0, 1]).all()


class TestMeanReversionSignals:
    def test_generate_signals_shape(self) -> None:
        from strategies.mean_reversion import generate_signals

        data = _make_ohlcv(100)
        signals = generate_signals(data)

        assert "signal" in signals.columns
        assert "zscore" in signals.columns
        assert "bb_upper" in signals.columns
        assert len(signals) == len(data)

    def test_signals_are_valid(self) -> None:
        from strategies.mean_reversion import generate_signals

        data = _make_ohlcv(200)
        signals = generate_signals(data)

        assert signals["signal"].isin([-1, 0, 1]).all()


class TestTrendFollowingSignals:
    def test_generate_signals_shape(self) -> None:
        from strategies.trend_following import generate_signals

        data = _make_ohlcv(250)
        signals = generate_signals(data)

        assert "signal" in signals.columns
        assert "adx" in signals.columns
        assert "fast_ma" in signals.columns
        assert len(signals) == len(data)

    def test_signals_are_valid(self) -> None:
        from strategies.trend_following import generate_signals

        data = _make_ohlcv(300)
        signals = generate_signals(data)

        assert signals["signal"].isin([-1, 0, 1]).all()


class TestOptionsVolatilitySignals:
    def test_generate_signals_shape(self) -> None:
        from strategies.options_volatility import generate_signals

        data = _make_ohlcv(300)
        signals = generate_signals(data)

        assert "signal" in signals.columns
        assert "hv" in signals.columns
        assert "iv_rank" in signals.columns
        assert len(signals) == len(data)

    def test_signals_are_valid(self) -> None:
        from strategies.options_volatility import generate_signals

        data = _make_ohlcv(300)
        signals = generate_signals(data)

        assert signals["signal"].isin([-1, 0, 1]).all()


class TestMACrossoverConfirmedSignals:
    """Tests for the confirmed MA crossover strategy (all three modes)."""

    def test_generate_signals_shape_iqr_avg(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(200)
        config = MACrossoverConfig(signal_mode="iqr_avg")
        signals = generate_signals(data, config)

        assert "signal" in signals.columns
        assert "short_ma" in signals.columns
        assert "long_ma" in signals.columns
        assert "bb_upper" in signals.columns
        assert len(signals) == len(data)

    def test_generate_signals_shape_iqr_highlow(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(200)
        config = MACrossoverConfig(signal_mode="iqr_highlow")
        signals = generate_signals(data, config)

        assert "signal" in signals.columns
        assert len(signals) == len(data)

    def test_generate_signals_shape_bollinger(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(200)
        config = MACrossoverConfig(signal_mode="bollinger")
        signals = generate_signals(data, config)

        assert "signal" in signals.columns
        assert len(signals) == len(data)

    def test_signals_are_valid_all_modes(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(300)
        for mode in ("iqr_avg", "iqr_highlow", "bollinger"):
            config = MACrossoverConfig(signal_mode=mode)
            signals = generate_signals(data, config)
            assert signals["signal"].isin([-1, 0, 1]).all(), f"Invalid signal values in mode {mode}"

    def test_invalid_mode_raises(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(100)
        config = MACrossoverConfig(signal_mode="invalid")
        with pytest.raises(ValueError, match="signal_mode"):
            generate_signals(data, config)

    def test_custom_ma_periods(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig

        data = _make_ohlcv(200)
        config = MACrossoverConfig(short_ma_period=5, long_ma_period=15)
        signals = generate_signals(data, config)

        assert signals["signal"].isin([-1, 0, 1]).all()

    def test_backtest_integration(self) -> None:
        from strategies.ma_crossover_confirmed import generate_signals, MACrossoverConfig
        from infrastructure.backtesting import BacktestEngine, BacktestConfig

        data = _make_ohlcv(300)
        config = MACrossoverConfig(signal_mode="iqr_avg", iqr_multiplier=0.5)
        signals = generate_signals(data, config)
        engine = BacktestEngine(BacktestConfig(initial_capital=100_000))
        result = engine.run(data, signals, "TEST")

        assert "sharpe_ratio" in result.metrics
        assert result.metrics["initial_capital"] == 100_000


class TestRiskManagement:
    def test_validate_order_passes(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig(max_position_pct=0.05, max_open_positions=20)
        from infrastructure.risk_management import RiskState
        rm.state = RiskState()

        valid, reason = rm.validate_order(
            symbol="AAPL", side="buy", quantity=10,
            price=150.0, account_equity=100_000, buying_power=50_000
        )
        assert valid is True

    def test_validate_order_exceeds_position_limit(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig, RiskState

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig(max_position_pct=0.01)
        rm.state = RiskState()

        valid, reason = rm.validate_order(
            symbol="AAPL", side="buy", quantity=100,
            price=150.0, account_equity=100_000, buying_power=50_000
        )
        assert valid is False
        assert "exceeds" in reason.lower()

    def test_validate_order_zero_quantity(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig, RiskState

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig()
        rm.state = RiskState()

        valid, reason = rm.validate_order(
            symbol="AAPL", side="buy", quantity=0,
            price=150.0, account_equity=100_000, buying_power=50_000
        )
        assert valid is False

    def test_position_sizing(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig, RiskState

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig(max_position_pct=0.05)
        rm.state = RiskState()

        shares = rm.calculate_position_size(100_000, 150.0, signal_strength=1.0)
        max_value = 100_000 * 0.05
        assert shares == int(max_value / 150.0)
        assert shares > 0

    def test_stop_loss_calculation(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig, RiskState

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig(default_stop_loss_pct=0.02)
        rm.state = RiskState()

        sl_long = rm.calculate_stop_loss(100.0, "long")
        assert sl_long == pytest.approx(98.0)

        sl_short = rm.calculate_stop_loss(100.0, "short")
        assert sl_short == pytest.approx(102.0)

    def test_daily_loss_halt(self) -> None:
        from infrastructure.risk_management import RiskManager, RiskConfig, RiskState

        rm = RiskManager.__new__(RiskManager)
        rm.config = RiskConfig(max_portfolio_loss_daily_pct=0.03)
        rm.state = RiskState(daily_start_equity=100_000)

        # 2% loss — should still be OK
        assert rm.check_daily_loss_limit(98_000) is True

        # 4% loss — should halt
        assert rm.check_daily_loss_limit(96_000) is False
        assert rm.state.trading_halted is True
