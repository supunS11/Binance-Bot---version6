import pandas as pd
import numpy as np


def apply_indicators(df):

    try:

        df = df.copy()

        # =========================
        # EMA
        # =========================
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        # =========================
        # RSI (UNCHANGED LOGIC)
        # =========================
        delta = df['close'].diff()

        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()

        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        # =========================
        # MACD
        # =========================
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()

        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # =========================
        # TRUE RANGE (FIXED)
        # =========================
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # =========================
        # ATR (STABLE VERSION)
        # =========================
        df['atr'] = tr.rolling(14).mean()

        # =========================
        # ADX (FIXED - REAL VERSION)
        # =========================
        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        atr = df['atr']

        plus_di = 100 * (plus_dm.rolling(14).mean() / (atr + 1e-10))
        minus_di = 100 * (minus_dm.rolling(14).mean() / (atr + 1e-10))

        dx = (
            abs(plus_di - minus_di) /
            (plus_di + minus_di + 1e-10)
        ) * 100

        df['adx'] = dx.rolling(14).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        df['di_spread'] = plus_di - minus_di
        df['adx_slope'] = df['adx'] - df['adx'].shift(3)

        # =========================
        # TREND EFFICIENCY
        # =========================
        efficiency_lookback = 10
        directional_change = df['close'].diff(efficiency_lookback).abs()
        path_change = (
            df['close']
            .diff()
            .abs()
            .rolling(efficiency_lookback)
            .sum()
        )
        df['efficiency_ratio'] = (
            directional_change / (path_change + 1e-10)
        ).clip(lower=0, upper=1)

        # =========================
        # VOLUME SMA
        # =========================
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / (df['volume_sma'] + 1e-10)

        # =========================
        # UTC SESSION VWAP
        # =========================
        typical_price = (high + low + close) / 3
        price_volume = typical_price * df['volume']

        if 'time' in df.columns:
            numeric_time = pd.to_numeric(df['time'], errors='coerce')
            unit = 'ms' if numeric_time.abs().max() > 10_000_000_000 else 's'
            session_time = pd.to_datetime(
                numeric_time,
                unit=unit,
                errors='coerce',
                utc=True
            )
            session_key = session_time.dt.floor('D')
            cumulative_volume = df['volume'].groupby(session_key).cumsum()
            cumulative_price_volume = price_volume.groupby(session_key).cumsum()
            df['session_vwap'] = (
                cumulative_price_volume / (cumulative_volume + 1e-10)
            )
        else:
            rolling_volume = df['volume'].rolling(96, min_periods=1).sum()
            rolling_price_volume = price_volume.rolling(
                96,
                min_periods=1
            ).sum()
            df['session_vwap'] = (
                rolling_price_volume / (rolling_volume + 1e-10)
            )

        df['atr_pct'] = (df['atr'] / (df['close'] + 1e-10)) * 100

        # =========================
        # CLEAN
        # =========================
        df.dropna(inplace=True)

        return df

    except Exception as e:
        print(f"INDICATORS ERROR: {e}")
        return None
