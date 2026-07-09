import requests
import json
import yfinance as yf
from datetime import datetime
import fear_greed
import pandas as pd
import cloudscraper

# ==============================================================================
# KONFIGURATION & API KEYS
# ==============================================================================
FRED_API_KEY = "ab6f0ccd2c13199cce48df867d1c9701"
OUTPUT_FILE = "dashboard_data.json"

# ==============================================================================
# HILFSFUNKTIONEN FÜR DATENABRUF & BERECHNUNGEN
# ==============================================================================

def get_fred_data(series_id, api_key):
    """Holt den aktuellsten Wert einer Datenreihe aus der FRED Datenbank."""
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        value = response.json()['observations'][0]['value']
        if value == '.':
            url_fallback = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=5"
            fallback_data = requests.get(url_fallback, timeout=10).json()
            for obs in fallback_data['observations']:
                if obs['value'] != '.': return float(obs['value'])
            return None
        return float(value)
    except Exception: 
        return None

def get_trend_data(ticker_symbol):
    """Berechnet den prozentualen Abstand des Kurses zur 200-Tage-Linie (SMA 200)"""
    try:
        hist = yf.Ticker(ticker_symbol).history(period="1y")
        if hist.empty: return None
        current_price = hist['Close'].iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        return round(((current_price - sma_200) / sma_200) * 100, 2)
    except Exception: 
        return None

def get_macd_signal(ticker_symbol):
    """Berechnet den MACD und generiert exakte textbasierte Signale für das Dashboard"""
    try:
        hist = yf.Ticker(ticker_symbol).history(period="1y")
        if hist.empty: return None
        
        # MACD Berechnung
        exp1 = hist['Close'].ewm(span=12, adjust=False).mean()
        exp2 = hist['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal

        # Signal-Logik (Vergleich heute vs. gestern)
        m_today, m_yest = macd.iloc[-1], macd.iloc[-2]
        s_today, s_yest = signal.iloc[-1], signal.iloc[-2]
        h_today, h_yest = histogram.iloc[-1], histogram.iloc[-2]

        if m_yest < s_yest and m_today > s_today: return "Kreuzt von unten nach oben"
        elif m_yest > s_yest and m_today < s_today: return "Kreuzt von oben nach unten"
        elif h_today > h_yest and h_today > 0: return "Steigt steil"
        elif h_today > 0 and h_today <= h_yest: return "Steigt flach"
        elif h_today < h_yest and h_today < 0: return "Fällt stark"
        elif h_today < 0 and h_today >= h_yest: return "Fällt leicht"
        else: return "Neutral"
    except Exception: 
        return None

def get_vix_data(vix_ticker, index_fallback):
    """
    Holt den echten VIX. Falls Yahoo meckert (was bei EU und Japan oft passiert), 
    fängt das Skript den Fehler ab und berechnet ihn mathematisch selbst.
    """
    try:
        hist = yf.Ticker(vix_ticker).history(period="1mo")
        if not hist.empty and not hist['Close'].isna().all():
            return round(hist['Close'].dropna().iloc[-1], 2)
    except Exception:
        pass
        
    try:
        # Fallback: Realisierte Vola
        hist = yf.Ticker(index_fallback).history(period="3mo")
        if hist.empty: return None
        hist['Returns'] = hist['Close'].pct_change()
        vol = hist['Returns'].tail(30).std() * (252 ** 0.5) * 100
        return round(vol, 2)
    except Exception: 
        return None

def get_rsi(ticker_symbol, periods=14):
    """
    Berechnet den Relative Strength Index (RSI). 
    Skala: 0 (Extreme Fear/Überverkauft) bis 100 (Extreme Greed/Überkauft).
    """
    try:
        hist = yf.Ticker(ticker_symbol).history(period="6mo")
        if hist.empty: return None
        
        close_delta = hist['Close'].diff()
        
        up = close_delta.clip(lower=0)
        down = -1 * close_delta.clip(upper=0)
        
        ma_up = up.ewm(com=periods - 1, adjust=False).mean()
        ma_down = down.ewm(com=periods - 1, adjust=False).mean()
        
        rs = ma_up / ma_down
        rsi = 100 - (100 / (1 + rs))
        
        return int(round(rsi.iloc[-1]))
    except Exception:
        return None

def get_us_fear_and_greed():
    """
    Level 2 Panzer-Modus: Nutzt Cloudscraper, um sich als echter Browser 
    auszugeben und die CNN Firewall zu umgehen.
    """
    # Methode 1: Cloudscraper (Tarnkappen-Browser)
    try:
        scraper = cloudscraper.create_scraper()
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed"
        }
        response = scraper.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return round(float(data['fear_and_greed']['score']))
    except Exception:
        pass

    # Methode 2: Fallback auf das fear_greed Paket
    try:
        fg = fear_greed.get()
        if isinstance(fg, dict):
            if 'fear_and_greed' in fg and 'score' in fg['fear_and_greed']:
                return round(float(fg['fear_and_greed']['score']))
            val = fg.get('score', fg.get('value'))
            if val is not None:
                return round(float(val))
        elif hasattr(fg, 'score'):
            return round(float(fg.score))
        elif hasattr(fg, 'value'):
            return round(float(fg.value))
    except Exception as e:
        print(f"  -> Fehler beim Abruf des Fear & Greed Index: {e}")
        
    return None

# ==============================================================================
# HAUPTPROZESS
# ==============================================================================

def update_dashboard_data():
    print("Starte globalen Datenabruf (4 Regionen)...")
    
    # Globales Klima (CNN F&G)
    global_fg = get_us_fear_and_greed()
    
    # 1. USA
    print("-> Lade USA...")
    usa_data = {
        "trend": get_trend_data('^GSPC'),
        "macd": get_macd_signal('^GSPC'),
        "yield_curve": get_fred_data('T10Y2Y', FRED_API_KEY),
        "vix": get_vix_data('^VIX', '^GSPC'), 
        "credit_spread": get_fred_data('BAMLH0A0HYM2', FRED_API_KEY),
        "rsi": get_rsi('^GSPC') 
    }
    
    # 2. EUROPA
    print("-> Lade Europa...")
    eu_10y = get_fred_data('IRLTLT01EZM156N', FRED_API_KEY)
    eu_3m = get_fred_data('IR3TIB01EZM156N', FRED_API_KEY)
    eu_data = {
        "trend": get_trend_data('^STOXX'),
        "macd": get_macd_signal('^STOXX'),
        "yield_curve": round(eu_10y - eu_3m, 2) if eu_10y and eu_3m else None,
        "vix": get_vix_data('^V2TX', '^STOXX'),
        "credit_spread": get_fred_data('BAMLHE00EHYIOAS', FRED_API_KEY),
        "rsi": get_rsi('^STOXX') 
    }

    # 3. JAPAN (Sonderfall Developed Market)
    print("-> Lade Japan...")
    jp_10y = get_fred_data('IRLTLT01JPM156N', FRED_API_KEY)
    jp_3m = get_fred_data('IR3TIB01JPM156N', FRED_API_KEY)
    jp_data = {
        "trend": get_trend_data('^N225'),
        "macd": get_macd_signal('^N225'),
        "yield_curve": round(jp_10y - jp_3m, 2) if jp_10y and jp_3m else None,
        "vix": get_vix_data('^JNIV', '^N225'), 
        "credit_spread": None, 
        "rsi": get_rsi('^N225')
    }

    # 4. EMERGING MARKETS (ex China)
    print("-> Lade EM (ex China)...")
    em_data = {
        "trend": get_trend_data('EMXC'),
        "macd": get_macd_signal('EMXC'),
        "dxy_trend": get_trend_data('DX-Y.NYB'), 
        "vix": get_vix_data('^VXEEM', 'EMXC'),
        "credit_spread": get_fred_data('BAMLEMCBPIOAS', FRED_API_KEY),
        "rsi": get_rsi('EMXC')
    }

    # DATENOBJEKT ERSTELLEN
    dashboard_data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "global_fear_greed": global_fg,
        "usa": usa_data,
        "eu": eu_data,
        "japan": jp_data,
        "em": em_data
    }

    # DATEN IN JSON DATEI SPEICHERN
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, indent=4)
        
    print(f"Erfolgreich! Daten für alle 4 Regionen gespeichert in '{OUTPUT_FILE}'")

if __name__ == "__main__":
    update_dashboard_data()