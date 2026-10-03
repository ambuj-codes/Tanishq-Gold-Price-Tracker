import os
import re
from datetime import datetime, timezone, timedelta
from curl_cffi import requests
from bs4 import BeautifulSoup

ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "12750.0"))

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def get_ist_now():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    return now.strftime("%d-%b-%Y"), now.strftime("%I:%M %p IST")


def extract_price(text: str):
    """Extracts 22K 1G or 10G gold rate from scraped text."""
    # Check 1 Gram rate
    p_1g = re.search(
        r"22\s*(?:Kt|Karat|K)[\s\S]{1,250}?1\s*G(?:ram)?[\s\S]{1,60}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if p_1g:
        val = float(p_1g.group(1).replace(",", ""))
        if 5000 <= val <= 35000:
            return val

    # Check 10 Gram rate and divide by 10
    p_10g = re.search(
        r"22\s*(?:Kt|Karat|K)[\s\S]{1,250}?10\s*G(?:rams)?[\s\S]{1,60}?₹?\s*([\d,]{5,8}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if p_10g:
        val10 = float(p_10g.group(1).replace(",", ""))
        per_g = val10 / 10.0
        if 5000 <= per_g <= 35000:
            return per_g

    # General pattern matching
    p_all = re.findall(r"22\s*(?:Kt|Karat|K)[\s\S]{1,60}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)", text, re.IGNORECASE)
    for match in p_all:
        clean = float(match.replace(",", ""))
        if 5000 <= clean <= 35000:
            return clean

    return None


def fetch_tanishq_rate():
    sources = [
        {"name": "Tanishq Official", "url": "https://www.tanishq.co.in/gold-rate.html?lang=en_IN"},
        {"name": "Mia by Tanishq", "url": "https://www.miabytanishq.com/en_IN/gold-rate-today"},
        # Resilient mirror reporting official Tanishq / 22K benchmark rates in India
        {"name": "GoodReturns (22K India Rate)", "url": "https://www.goodreturns.in/gold-rates/"},
    ]

    for src in sources:
        try:
            print(f"Connecting to {src['name']}...")
            # impersonate='chrome124' mimics Chrome's exact TLS signature and bypasses 403
            resp = requests.get(
                src["url"],
                headers=HEADERS,
                impersonate="chrome124",
                timeout=25,
            )
            print(f"[{src['name']}] HTTP Status: {resp.status_code}")

            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Check table structures
            for tr in soup.find_all("tr"):
                row = tr.get_text(" ", strip=True)
                if "22" in row and ("1" in row or "gram" in row.lower()):
                    matches = re.findall(r"₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)", row)
                    for m in matches:
                        num = float(m.replace(",", ""))
                        if 5000 <= num <= 35000:
                            print(f"Extracted ₹{num} from table on {src['name']}")
                            return num, src["name"]

            # Fallback to regex scanning
            rate = extract_price(soup.get_text(" ", strip=True))
            if rate:
                print(f"Extracted ₹{rate} from text on {src['name']}")
                return rate, src["name"]

        except Exception as e:
            print(f"Error accessing {src['name']}: {e}")

    return None, None


def main():
    date_str, time_str = get_ist_now()
    full_timestamp = f"{date_str} at {time_str}"
    rate, source_name = fetch_tanishq_rate()

    history_file = "gold_rate_history.csv"
    if not os.path.exists(history_file):
        with open(history_file, "w", encoding="utf-8") as f:
            f.write("Date,Time_IST,Purity,Rate_Per_Gram_INR,Status,Source\n")

    if rate is None:
        subject = f"⚠️ [ERROR] Tanishq Gold Tracker Failed ({full_timestamp})"
        body = (
            f"Automated check failed at {full_timestamp}.\n"
            f"Both Tanishq and backup mirrors returned connection errors.\n"
            f"Check GitHub Actions logs for details."
        )
        with open("commit_message.txt", "w", encoding="utf-8") as f:
            f.write(f"{subject}\n\n{body}\n")
        with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
            f.write(f"Last Attempt: {full_timestamp}\nStatus: Failed to retrieve rates\n")
        return

    is_drop = rate < ALERT_THRESHOLD
    diff = ALERT_THRESHOLD - rate

    if is_drop:
        subject = f"🚨 [ALERT] Tanishq 22K Gold Dropped to ₹{rate:,.2f}/g!"
        status_line = f"ALERT: Price is ₹{diff:,.2f} BELOW threshold (₹{ALERT_THRESHOLD:,.2f})!"
        csv_status = "BELOW_THRESHOLD_ALERT"
    else:
        subject = f"📊 [Daily Update] Tanishq 22K Gold: ₹{rate:,.2f}/g"
        status_line = f"Normal: Price is ₹{abs(diff):,.2f} above threshold (₹{ALERT_THRESHOLD:,.2f})"
        csv_status = "ABOVE_THRESHOLD"

    body = (
        f"========================================\n"
        f" TANISHQ 22 KARAT GOLD RATE UPDATE\n"
        f"========================================\n"
        f"Checked On      : {full_timestamp}\n"
        f"22K Gold Rate   : ₹{rate:,.2f} per gram\n"
        f"Alert Threshold : ₹{ALERT_THRESHOLD:,.2f} per gram\n"
        f"Status          : {status_line}\n"
        f"Source          : {source_name}\n"
        f"========================================\n"
    )

    with open("commit_message.txt", "w", encoding="utf-8") as f:
        f.write(f"{subject}\n\n{body}\n")

    with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
        f.write(body)

    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"{date_str},{time_str},22 Karat,{rate:.2f},{csv_status},{source_name}\n")

    print(f"Processed rate: ₹{rate:,.2f}/g from {source_name}")


if __name__ == "__main__":
    main()
