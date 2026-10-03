import os
import re
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# Alert threshold for 22 Karat gold per gram (INR)
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "13750.0"))

OFFICIAL_TANISHQ_URL = "https://www.tanishq.co.in/gold-rate.html?lang=en_IN"


def get_ist_now():
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    return now.strftime("%d-%b-%Y"), now.strftime("%I:%M %p IST")


def extract_22k_price(text: str):
    """
    Parses the 22 Karat 1 Gram gold rate from Tanishq's rendered text.
    Handles table rows, markdown tables, and inline key-value pairs.
    """
    # Pattern 1: Look for 22K block followed by 1 Gram price
    p_1g = re.search(
        r"22\s*(?:Karat|Kt|K)[\s\S]{1,200}?(?:1\s*Gram|1\s*g|1\s*G)[\s\S]{1,80}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if p_1g:
        val = float(p_1g.group(1).replace(",", ""))
        if 5000 <= val <= 35000:
            return val

    # Pattern 2: Look for 1 Gram row where 22K is the column header
    p_row = re.search(
        r"(?:1\s*Gram|1\s*g|1\s*G)[\s\S]{1,120}?22\s*(?:Karat|Kt|K)[\s\S]{1,80}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if p_row:
        val = float(p_row.group(1).replace(",", ""))
        if 5000 <= val <= 35000:
            return val

    # Pattern 3: Standard 22 Karat rate declaration
    p_direct = re.findall(
        r"22\s*(?:Karat|Kt|K)[\s\S]{1,60}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    for match in p_direct:
        val = float(match.replace(",", ""))
        if 5000 <= val <= 35000:
            return val

    # Pattern 4: 10 Gram 22K rate divided by 10 (common backup on Indian jewelers)
    p_10g = re.search(
        r"22\s*(?:Karat|Kt|K)[\s\S]{1,200}?(?:10\s*Grams|10\s*g|10\s*G)[\s\S]{1,80}?₹?\s*([\d,]{5,8}(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if p_10g:
        val10 = float(p_10g.group(1).replace(",", ""))
        per_g = val10 / 10.0
        if 5000 <= per_g <= 35000:
            return per_g

    return None


def fetch_tanishq_rate():
    # Route official Tanishq through edge headless rendering to bypass Akamai 403 & execute JS
    endpoints = [
        {
            "name": "Tanishq Official (Edge Rendered)",
            "url": f"https://r.jina.ai/{OFFICIAL_TANISHQ_URL}",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-Wait-For-Selector": "table",
            },
        },
        {
            "name": "Tanishq Official (Direct)",
            "url": OFFICIAL_TANISHQ_URL,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        },
    ]

    for ep in endpoints:
        try:
            print(f"Connecting to: {ep['name']}...")
            resp = requests.get(ep["url"], headers=ep["headers"], timeout=30)
            print(f"Status Code: {resp.status_code}")

            if resp.status_code != 200:
                print(f"Received non-200 response ({resp.status_code}). Skipping...")
                continue

            content = resp.text

            # Parse through text representation
            rate = extract_22k_price(content)
            if rate:
                print(f"Successfully extracted Tanishq 22K rate: ₹{rate:,.2f}/g via {ep['name']}")
                return rate, "Tanishq Official (https://www.tanishq.co.in/gold-rate.html)"

            # If plain regex fails, inspect HTML tags (in case Direct returned 200)
            soup = BeautifulSoup(content, "html.parser")
            for tr in soup.find_all("tr"):
                row_str = tr.get_text(" ", strip=True)
                if "22" in row_str and ("1" in row_str or "gram" in row_str.lower()):
                    nums = re.findall(r"₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)", row_str)
                    for n in nums:
                        clean_num = float(n.replace(",", ""))
                        if 5000 <= clean_num <= 35000:
                            print(f"Extracted from HTML table: ₹{clean_num:,.2f}")
                            return clean_num, "Tanishq Official (HTML Table)"

        except Exception as e:
            print(f"Error checking {ep['name']}: {e}")

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
            f"Unable to parse 22K price from official Tanishq page.\n"
            f"Review GitHub Actions execution logs for raw output."
        )
        with open("commit_message.txt", "w", encoding="utf-8") as f:
            f.write(f"{subject}\n\n{body}\n")
        with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
            f.write(f"Last Attempt: {full_timestamp}\nStatus: Extraction Failed\n")
        return

    is_drop = rate < ALERT_THRESHOLD
    diff = ALERT_THRESHOLD - rate

    if is_drop:
        subject = f"🚨 [ALERT] Official Tanishq 22K Gold: ₹{rate:,.2f}/g!"
        status_line = f"ALERT: Price is ₹{diff:,.2f} BELOW threshold (₹{ALERT_THRESHOLD:,.2f})!"
        csv_status = "BELOW_THRESHOLD_ALERT"
    else:
        subject = f"📊 [Daily Update] Official Tanishq 22K Gold: ₹{rate:,.2f}/g"
        status_line = f"Normal: Price is ₹{abs(diff):,.2f} above threshold (₹{ALERT_THRESHOLD:,.2f})"
        csv_status = "ABOVE_THRESHOLD"

    body = (
        f"========================================\n"
        f" OFFICIAL TANISHQ 22K GOLD RATE UPDATE\n"
    
        f"Checked On      : {full_timestamp}\n"
        f"22K Gold Rate   : ₹{rate:,.2f} per gram\n"
        f"Alert Threshold : ₹{ALERT_THRESHOLD:,.2f} per gram\n"
        f"Status          : {status_line}\n"
        f"Source          : {source_name}\n"
        
    )

    with open("commit_message.txt", "w", encoding="utf-8") as f:
        f.write(f"{subject}\n\n{body}\n")

    with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
        f.write(body)

    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"{date_str},{time_str},22 Karat,{rate:.2f},{csv_status},{source_name}\n")

    print(f"Run completed successfully: ₹{rate:,.2f}/g.")


if __name__ == "__main__":
    main()
