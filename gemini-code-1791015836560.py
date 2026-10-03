import os
import re
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

# Alert threshold for 22 Karat gold per gram in INR
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "12750.0"))


def get_ist_now():
    """Returns current timestamp in Indian Standard Time (IST)."""
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    return now.strftime("%d-%b-%Y"), now.strftime("%I:%M %p IST")


def fetch_gold_rate():
    """Scrapes today's 22 Karat gold rate per gram from Tanishq."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    }

    urls = [
        "https://www.tanishq.co.in/gold-rate.html?lang=en_IN",
        "https://www.miabytanishq.com/en_IN/gold-rate-today",
    ]

    for url in urls:
        try:
            print(f"Checking Tanishq URL: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"Returned HTTP status {response.status_code}. Skipping...")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            page_text = soup.get_text(" ", strip=True)

            # Strategy 1: Table row matching 22K and 1g
            for tr in soup.find_all("tr"):
                row_str = tr.get_text(" ", strip=True)
                if "22" in row_str and ("1" in row_str or "1G" in row_str or "1g" in row_str):
                    matches = re.findall(r"₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)", row_str)
                    for m in matches:
                        clean_val = float(m.replace(",", ""))
                        if 5000 <= clean_val <= 30000:
                            print(f"Strategy 1 extracted: ₹{clean_val}")
                            return clean_val

            # Strategy 2: Text regex looking for 22 Kt/Karat followed by 1G price
            p1g = re.search(
                r"22\s*(?:Kt|Karat|K)[\s\S]{1,200}?1\s*G[\s\S]{1,60}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
                page_text,
                re.IGNORECASE,
            )
            if p1g:
                val = float(p1g.group(1).replace(",", ""))
                if 5000 <= val <= 30000:
                    print(f"Strategy 2 extracted: ₹{val}")
                    return val

            # Strategy 3: Check for 10 Grams 22K rate and divide by 10
            p10g = re.search(
                r"22\s*(?:Kt|Karat|K)[\s\S]{1,200}?10\s*G[\s\S]{1,60}?₹?\s*([\d,]{5,8}(?:\.\d{1,2})?)",
                page_text,
                re.IGNORECASE,
            )
            if p10g:
                val10 = float(p10g.group(1).replace(",", ""))
                per_gram = val10 / 10.0
                if 5000 <= per_gram <= 30000:
                    print(f"Strategy 3 extracted: ₹{per_gram} (from 10g)")
                    return per_gram

        except Exception as e:
            print(f"Encountered error fetching {url}: {e}")

    return None


def main():
    date_str, time_str = get_ist_now()
    full_timestamp = f"{date_str} at {time_str}"
    rate = fetch_gold_rate()

    # Ensure historical log ledger exists
    history_file = "gold_rate_history.csv"
    if not os.path.exists(history_file):
        with open(history_file, "w", encoding="utf-8") as f:
            f.write("Date,Time_IST,Purity,Rate_Per_Gram_INR,Status\n")

    if rate is None:
        print("Could not retrieve rate from Tanishq.")
        subject = f"⚠️ [ERROR] Tanishq Gold Tracker Failed ({full_timestamp})"
        body = (
            f"Automated gold check failed at {full_timestamp}.\n"
            f"The scraper could not parse the price. Please check if Tanishq changed their site structure."
        )
        with open("commit_message.txt", "w", encoding="utf-8") as f:
            f.write(f"{subject}\n\n{body}\n")
        with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
            f.write(f"Last Attempt: {full_timestamp}\nStatus: Scraping Failed\n")
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
        f"Source          : https://www.tanishq.co.in/gold-rate.html?lang=en_IN\n"
        f"========================================\n"
    )

    print(f"\n--- Commit Message ---\nSubject: {subject}\n\n{body}")

    # 1. Write the Git commit message (Used as the Email subject and body by GitHub)
    with open("commit_message.txt", "w", encoding="utf-8") as f:
        f.write(f"{subject}\n\n{body}\n")

    # 2. Update latest_gold_rate.txt
    with open("latest_gold_rate.txt", "w", encoding="utf-8") as f:
        f.write(body)

    # 3. Append to historical CSV ledger
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(f"{date_str},{time_str},22 Karat,{rate:.2f},{csv_status}\n")

    print("Files updated successfully. Ready for commit & push.")


if __name__ == "__main__":
    main()