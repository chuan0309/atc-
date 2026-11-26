"""常見航空公司的無線電呼號（telephony）。沒列到的就念字母。"""
TELEPHONY = {
    "CAL": "Dynasty", "EVA": "Eva", "TTW": "Smart Cat", "SJX": "Starwalker", "MDA": "Mandarin",
    "CPA": "Cathay", "HKE": "Hong Kong Shuttle", "JAL": "Japanair", "ANA": "All Nippon",
    "APJ": "Air Peach", "KAL": "Korean Air", "AAR": "Asiana", "CCA": "Air China",
    "CES": "China Eastern", "CSN": "China Southern", "SIA": "Singapore", "THA": "Thai",
    "VJC": "Vietjet", "HVN": "Viet Nam Airlines", "PAL": "Philippine", "MAS": "Malaysian",
    "QFA": "Qantas", "UAE": "Emirates", "QTR": "Qatari", "ETD": "Etihad",
    "AAL": "American", "UAL": "United", "DAL": "Delta", "SWA": "Southwest", "ASA": "Alaska",
    "JBU": "Jetblue", "ACA": "Air Canada", "BAW": "Speedbird", "VIR": "Virgin",
    "DLH": "Lufthansa", "AFR": "Airfrance", "KLM": "KLM", "RYR": "Ryanair", "EZY": "Easy",
    "THY": "Turkish", "FDX": "Fedex", "UPS": "UPS", "GTI": "Giant",
}

ALPHABET = {c: w for c, w in zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "Alfa Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima Mike November "
    "Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey Xray Yankee Zulu".split())}


def radio_callsign(airline: str, number: str) -> str:
    name = TELEPHONY.get(airline.upper()) or " ".join(ALPHABET.get(c, c) for c in airline.upper())
    return f"{name} {number}"
