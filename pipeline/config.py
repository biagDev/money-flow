"""MONEY FLOW — central configuration.
Every tunable lives here. Logic files never hardcode a threshold.
"""

FRED_BASE = "https://api.stlouisfed.org/fred"

# ---- FRED series --------------------------------------------------------
FRED_SERIES = {
    # Fed stance
    "fed_target_upper": "DFEDTARU",     # daily, target range upper
    "fed_funds": "FEDFUNDS",            # monthly effective
    # Inflation dial
    "pce": "PCEPI",                     # index -> compute YoY
    "cpi": "CPIAUCSL",                  # index -> compute YoY
    "ppi": "PPIACO",                    # index -> compute YoY
    "breakeven_5y": "T5YIE",            # daily
    "oil": "DCOILWTICO",                # daily WTI
    # Employment dial
    "unrate": "UNRATE",
    "payems": "PAYEMS",                 # level -> MoM delta = NFP (thousands)
    "claims": "ICSA",                   # weekly initial claims
    "jolts": "JTSJOL",                  # openings (thousands)
    # Yield curve
    "y3m": "DGS3MO", "y2": "DGS2", "y5": "DGS5", "y10": "DGS10", "y30": "DGS30",
    "spread_10y3m": "T10Y3M",
    "spread_10y2y": "T10Y2Y",
    # Real yields
    "real_5y": "DFII5",
    "real_10y": "DFII10",
    # Liquidity & context
    "walcl": "WALCL",                   # Fed balance sheet, weekly
    "vix": "VIXCLS",
    "recessions": "USREC",              # 1/0 monthly, for shading + backtest
    # Prices (FRED has these daily — avoids a second vendor for core assets)
    # NOTE: FRED retired its LBMA gold series (GOLDPMGBD228NLBM) over licensing —
    # the API now 400s on it. Gold comes from the fetch_prices fallback instead,
    # exactly as the original comment anticipated. Deliberately absent here.
    "dxy_proxy": "DTWEXBGS",            # broad dollar index (trade-weighted)
    "spx": "SP500",                     # S&P 500 (FRED licenses last 10y)
}

# ---- Regime engine ------------------------------------------------------
REGIMES = ["expansion", "peak", "contraction", "recovery"]

WEIGHTS = {
    "inflation":   0.30,
    "employment":  0.25,
    "fed_stance":  0.20,
    "yield_curve": 0.15,
    "liquidity":   0.10,
}

THRESHOLDS = {
    "inflation_target": 2.0,        # PCE YoY %
    "inflation_hot": 2.5,           # decisively above target
    "inflation_momentum": 0.15,     # pp per 3mo considered "rising/falling"
    "sahm_trigger": 0.50,           # UNRATE 3mo-avg above 12mo low (pp)
    "sahm_warning": 0.20,
    "curve_flat": 0.50,             # 10Y-3M below this = flattening zone (pp)
    "curve_steepen_3mo": 0.25,      # post-inversion steepening speed (pp/3mo)
    "walcl_6mo_pct": 0.0,           # >0 expanding, <0 contracting
    "fed_move_stale_days": 365,     # a rate move older than this stops implying direction
    "projection_lags_months": [1, 2, 3],
}

# ---- Prices (non-FRED vendor: gold + ZQ fed-funds futures) --------------
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
GOLD_SYMBOL = "GC=F"        # COMEX gold front month (FRED no longer carries spot)
GOLD_HISTORY = "5y"         # evidence charts need 5y of daily closes

# ---- CFTC COT -----------------------------------------------------------
COT_SOCRATA = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"  # legacy futures-only
COT_MARKETS = {
    "gold":   "GOLD - COMMODITY EXCHANGE INC.",
    "dxy":    "USD INDEX - ICE FUTURES U.S.",
    "spx":    "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "tnote10":"UST 10Y NOTE - CHICAGO BOARD OF TRADE",
    "eur":    "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "jpy":    "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "aud":    "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
}
COT_WEEKS = 104          # history shown
COT_PCTILE_WEEKS = 156   # percentile window

# ---- Scenario decks (framework constants; live trends merged at build) --
SCENARIO_DECKS = {
    "hike": [
        {"asset": "bonds",  "label": "Bond yields", "dir": "up",
         "why": "New debt must pay more; the short end jumps hardest."},
        {"asset": "dollar", "label": "US Dollar",   "dir": "up",
         "why": "Banks park cash where risk-free yield is highest."},
        {"asset": "gold",   "label": "Gold",        "dir": "down",
         "why": "Real yields rise — bonds out-compete gold as the inflation hedge."},
        {"asset": "stocks", "label": "Stocks",      "dir": "caution",
         "why": "Can grind higher until something breaks; watch the curve."},
        {"asset": "curve",  "label": "Yield curve", "dir": "flatten",
         "why": "Overnight-rate pressure on the short end — the historic recession precursor."},
    ],
    "cut": [
        {"asset": "bonds",  "label": "Bond yields", "dir": "down",
         "why": "Cheaper money; existing bonds rally as yields fall."},
        {"asset": "dollar", "label": "US Dollar",   "dir": "down",
         "why": "Yield advantage evaporates; capital hunts returns elsewhere."},
        {"asset": "gold",   "label": "Gold",        "dir": "up",
         "why": "Real yields fall — gold wins the safe-haven contest."},
        {"asset": "stocks", "label": "Stocks",      "dir": "up",
         "why": "Cheap credit → borrowing → earnings → risk appetite (once the reason for cutting passes)."},
        {"asset": "curve",  "label": "Yield curve", "dir": "steepen",
         "why": "Short end drops first; steepening after inversion is the classic recession confirmation."},
    ],
    "hold": [
        {"asset": "bonds",  "label": "Bond yields", "dir": "drift",
         "why": "Direction inherits from the expectation trend, not the meeting."},
        {"asset": "dollar", "label": "US Dollar",   "dir": "drift",
         "why": "Follows the next expected move — watch the two dials."},
        {"asset": "gold",   "label": "Gold",        "dir": "drift",
         "why": "Tracks real-yield expectations while the Fed waits."},
        {"asset": "stocks", "label": "Stocks",      "dir": "up",
         "why": "Structural upward skew persists absent a shock."},
        {"asset": "curve",  "label": "Yield curve", "dir": "drift",
         "why": "Shape set by which move markets price next."},
    ],
}

# Regime -> expected 3mo directions for the confirmation scorecard
REGIME_EXPECTATIONS = {
    "expansion": {"y10_bp": "up", "dxy": "down", "gold": "up",  "spx": "up",   "cot_gold": "up"},
    "peak":      {"y10_bp": "up", "dxy": "up",   "gold": "down","spx": "flat", "cot_gold": "down"},
    "contraction":{"y10_bp":"down","dxy": "up",  "gold": "down","spx": "down", "cot_gold": "down"},
    "recovery":  {"y10_bp": "down","dxy": "down","gold": "up",  "spx": "up",   "cot_gold": "up"},
}
SCORECARD_FLAT_BAND = {"y10_bp": 15.0, "dxy": 1.0, "gold": 1.5, "spx": 2.0}  # |move| below = "flat"

# Money-flow edges per regime (from -> to, strength 0..1)
REGIME_FLOWS = {
    "expansion":  [("bonds","stocks",0.8), ("dollar","gold",0.5), ("bonds","gold",0.4)],
    "peak":       [("gold","dollar",0.7), ("gold","bonds",0.5), ("stocks","dollar",0.3)],
    "contraction":[("stocks","bonds",0.9), ("gold","dollar",0.4), ("stocks","dollar",0.5)],
    "recovery":   [("dollar","gold",0.8), ("bonds","stocks",0.7), ("dollar","stocks",0.5)],
}

ASSET_DRIVERS = {
    "bonds":  "The market everything else keys off. Driver: Fed expectations.",
    "dollar": "Driver: bond yield differentials vs other currencies. ~90% of forex is this.",
    "gold":   "Driver: REAL yields (yield − inflation). Bonds are its competitor, not war headlines.",
    "stocks": "Driver: risk appetite + liquidity. Printed money tends to end up here.",
}

# ---- Calendar -----------------------------------------------------------
FRED_RELEASES = {          # release_id on FRED
    "CPI": 10,
    "PCE (Personal Income & Outlays)": 54,
    "Employment Situation (NFP)": 50,
    "JOLTS": 192,
    "Jobless Claims": 180,
    "GDP": 53,
    "PPI": 46,
}
RELEASE_FEEDS = {
    "CPI": "inflation", "PCE (Personal Income & Outlays)": "inflation", "PPI": "inflation",
    "Employment Situation (NFP)": "employment", "JOLTS": "employment",
    "Jobless Claims": "employment", "GDP": "both",
}
RELEASE_HINTS = {
    "inflation": "Hot print → strengthens hike case → dollar ▲ gold ▼",
    "employment": "Weak print → strengthens cut case → gold ▲ dollar ▼",
    "both": "Growth surprise shifts the whole regime read",
}
CALENDAR_LOOKAHEAD_DAYS = 14
CALENDAR_LOOKBACK_DAYS = 30

SCHEMA_VERSION = 1
