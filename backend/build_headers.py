"""
Build YouTube Music browser_headers.json from exported cookie JSON.
"""
import json
import hashlib
import time

COOKIES_JSON = [{"domain":".youtube.com","expirationDate":1803109609.720837,"hostOnly":False,"httpOnly":True,"name":"__Secure-1PSIDTS","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"sidts-CjQBBj1CYsjlY6N_9PVcPC-m8gHuU6e4E9kP1aPV65EYREW7bxMAH8zsxJv1fua_saH94mOvEAA"},{"domain":".youtube.com","expirationDate":1803109609.720974,"hostOnly":False,"httpOnly":True,"name":"__Secure-3PSIDTS","path":"/","sameSite":"no_restriction","secure":True,"session":False,"storeId":"0","value":"sidts-CjQBBj1CYsjlY6N_9PVcPC-m8gHuU6e4E9kP1aPV65EYREW7bxMAH8zsxJv1fua_saH94mOvEAA"},{"domain":".youtube.com","expirationDate":1806133609.721024,"hostOnly":False,"httpOnly":True,"name":"HSID","path":"/","sameSite":"unspecified","secure":False,"session":False,"storeId":"0","value":"Aw3nImhRbwOTyuLHR"},{"domain":".youtube.com","expirationDate":1806133609.7211,"hostOnly":False,"httpOnly":True,"name":"SSID","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"AUINGSosPsmJ2FC7u"},{"domain":".youtube.com","expirationDate":1806133609.72117,"hostOnly":False,"httpOnly":False,"name":"APISID","path":"/","sameSite":"unspecified","secure":False,"session":False,"storeId":"0","value":"HInJ69YSF8t-WiCK/AjmChNRekWrehhOWM"},{"domain":".youtube.com","expirationDate":1806133609.721247,"hostOnly":False,"httpOnly":False,"name":"SAPISID","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"9cgAqogsZmcfrNhL/A8NHyysnnzLuISUOK"},{"domain":".youtube.com","expirationDate":1806133609.721317,"hostOnly":False,"httpOnly":False,"name":"__Secure-1PAPISID","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"9cgAqogsZmcfrNhL/A8NHyysnnzLuISUOK"},{"domain":".youtube.com","expirationDate":1806133609.721409,"hostOnly":False,"httpOnly":False,"name":"__Secure-3PAPISID","path":"/","sameSite":"no_restriction","secure":True,"session":False,"storeId":"0","value":"9cgAqogsZmcfrNhL/A8NHyysnnzLuISUOK"},{"domain":".youtube.com","expirationDate":1806133609.721505,"hostOnly":False,"httpOnly":False,"name":"SID","path":"/","sameSite":"unspecified","secure":False,"session":False,"storeId":"0","value":"g.a0007AgMkqbnMjXe6-TRyFPDqSWY3DOTv6A3sc6wFJ-YcU3TrlqR4GdULuNP-zmtPqOOthONjgACgYKARESARUSFQHGX2MiPF7Lk6nNLqvPc3g4tJreZBoVAUF8yKobIK7Nf2Ai5BdBOEFSjqBR0076"},{"domain":".youtube.com","expirationDate":1806133609.721597,"hostOnly":False,"httpOnly":True,"name":"__Secure-1PSID","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"g.a0007AgMkqbnMjXe6-TRyFPDqSWY3DOTv6A3sc6wFJ-YcU3TrlqRZrBEFug4KuU0Gzn_MqGuOgACgYKAeISARUSFQHGX2MiZ35DozKNuO7iXPY_MJ2dnxoVAUF8yKoNrSjj9ZUzKyBC00oe1-hB0076"},{"domain":".youtube.com","expirationDate":1806133609.721683,"hostOnly":False,"httpOnly":True,"name":"__Secure-3PSID","path":"/","sameSite":"no_restriction","secure":True,"session":False,"storeId":"0","value":"g.a0007AgMkqbnMjXe6-TRyFPDqSWY3DOTv6A3sc6wFJ-YcU3TrlqRRQthOAj7b7KGhj8uV8DggAACgYKAX0SARUSFQHGX2MiSXZpG3qwKlLqJlvDxcMaChoVAUF8yKruU03BcytdpAFklFimy4Qs0076"},{"domain":".youtube.com","expirationDate":1806134550.614125,"hostOnly":False,"httpOnly":True,"name":"LOGIN_INFO","path":"/","sameSite":"no_restriction","secure":True,"session":False,"storeId":"0","value":"AFmmF2swRQIhAPcHmxLw9o2ku1c5NtuxfxHK7RI8qzTxPR8FpBk6DWHsAiADzbhlkTsgM3YfoM-A_aHlgi_q5RlnLpNA5TS0XDF7DA:QUQ3MjNmd2lXTUljRDJmMmxwRXJlbnpPWk82RlprVlJhZXZVWVJpMW8zYmFDSnFXTkFTNDhOYUN0ZGtxMGhhNGhpRDhfNHY4STRGVzJkSG80VXlCLU5VSjI4T0Z4eTkzOUY1MWU1MDZxRGxMNEh4UDBvQkl3cDdQTm55YTJtTWhVUzdFV2NZNlBVbUx1Vk1iajlhOTYyMFlzNU5UUU1SS0N3"},{"domain":".youtube.com","expirationDate":1807448896.754344,"hostOnly":False,"httpOnly":False,"name":"PREF","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"tz=Asia.Calcutta&f4=4000000&f6=40000000&f5=30000&f7=100&repeat=NONE"},{"domain":".youtube.com","expirationDate":1772889274,"hostOnly":False,"httpOnly":False,"name":"CONSISTENCY","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"AG2Tqf94v_S3I0UUuyTIbgQAmga6r0cFOcYsbv4kQrq_J7zuxa1EP7UMnSAQXGScNURms_uw_S6LwirFVuBqBdlBZZDYTygupqzMjD9I50ttlE5YB9TqTgYLYN8nNYLLSjk59g19uuKvFnHzmTsnyCaE"},{"domain":".youtube.com","expirationDate":1804424896.051849,"hostOnly":False,"httpOnly":False,"name":"SIDCC","path":"/","sameSite":"unspecified","secure":False,"session":False,"storeId":"0","value":"AKEyXzUUUCvQ-LCBbLB0vhZc7AJ0QrXehVhDtJ9osnmMNnzhnxrZJCZOrOdea-pVYNiKN1PlgQ"},{"domain":".youtube.com","expirationDate":1804424896.051981,"hostOnly":False,"httpOnly":True,"name":"__Secure-1PSIDCC","path":"/","sameSite":"unspecified","secure":True,"session":False,"storeId":"0","value":"AKEyXzVMw-JVL-QiaanGHCOh9L25hySM5JgUOOlwgW8zVu-ajPVAlmc7ObZkwWsAi1aEY2gTMlY"},{"domain":".youtube.com","expirationDate":1804424896.052053,"hostOnly":False,"httpOnly":True,"name":"__Secure-3PSIDCC","path":"/","sameSite":"no_restriction","secure":True,"session":False,"storeId":"0","value":"AKEyXzUBKzkISIjYJbD0MpQr1ViVrn-MezCEnUtJlhZMnOFjK2V9X5DD8KZc0Tn80TO4QuCiAw"}]

# Build cookie string from JSON
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in COOKIES_JSON)

# Extract SAPISID for computing SAPISIDHASH
sapisid = next((c['value'] for c in COOKIES_JSON if c['name'] == 'SAPISID'), None)
if not sapisid:
    sapisid = next((c['value'] for c in COOKIES_JSON if c['name'] == '__Secure-3PAPISID'), None)

ORIGIN = "https://music.youtube.com"

def compute_sapisidhash(sapisid_value, origin):
    ts = int(time.time())
    digest_input = f"{ts} {sapisid_value} {origin}"
    sha1 = hashlib.sha1(digest_input.encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{sha1}"

authorization = compute_sapisidhash(sapisid, ORIGIN)

headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0",
    "accept": "*/*",
    "accept-encoding": "gzip, deflate",
    "content-type": "application/json",
    "content-encoding": "gzip",
    "origin": ORIGIN,
    "cookie": cookie_str,
    "x-goog-authuser": "0",
    "authorization": authorization,
}

output_file = "browser_headers.json"
with open(output_file, "w") as f:
    json.dump(headers, f, indent=2)

# Save cookie expiry from auth-critical cookies (ignore short-lived/session cookies)
AUTH_COOKIES = {"SAPISID", "SSID", "SID", "__Secure-3PSID", "__Secure-1PSID"}
expiry_dates = [
    c.get("expirationDate") for c in COOKIES_JSON
    if c.get("expirationDate") and c.get("name") in AUTH_COOKIES
]
if not expiry_dates:
    expiry_dates = [c.get("expirationDate") for c in COOKIES_JSON if c.get("expirationDate")]
if expiry_dates:
    import datetime
    min_expiry = min(expiry_dates)
    with open("cookie_expiry.json", "w") as f:
        json.dump({"expires": int(min_expiry)}, f)
    exp_dt = datetime.datetime.fromtimestamp(min_expiry)
    days = (exp_dt - datetime.datetime.now()).days
    print(f"Cookie expiry: {exp_dt.strftime('%Y-%m-%d')} ({days} days from now)")

print(f"Saved {output_file}!")
print(f"SAPISID found: {sapisid[:20]}...")
print(f"Authorization: {authorization[:50]}...")

# Now test it
from ytmusicapi import YTMusic
try:
    yt = YTMusic(output_file)
    result = yt.get_home()
    print(f"\n✅ SUCCESS! YouTube Music authenticated. Home has {len(result)} sections.")
except Exception as e:
    print(f"\n❌ FAIL: {e}")
