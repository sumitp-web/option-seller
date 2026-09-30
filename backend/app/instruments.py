"""Maps F&O contracts to their underlying's spot symbol for quotes."""

# Index underlyings use a different quote symbol from their F&O "name".
INDEX_SPOT = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "NIFTYNXT50": "NSE:NIFTY NEXT 50",
    "SENSEX": "BSE:SENSEX",
    "BANKEX": "BSE:BANKEX",
    "SENSEX50": "BSE:SENSEX50",
}

FNO_EXCHANGES = ("NFO", "BFO")


def spot_symbol(name: str, exchange: str) -> str:
    if name in INDEX_SPOT:
        return INDEX_SPOT[name]
    return f"{'BSE' if exchange == 'BFO' else 'NSE'}:{name}"
