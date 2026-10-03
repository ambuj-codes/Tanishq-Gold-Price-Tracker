import os
import re
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

# --- Configuration ---
THRESHOLD_PRICE = float(os.getenv("ALERT_THRESHOLD", "12750.0"))
ALWAYS_NOTIFY = os.getenv("ALWAYS_NOTIFY", "true").lower() == "true"

# Email Configuration (e.g., Gmail SMTP)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")  # App Password if using Gmail
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

# SMS Configuration (Twilio - Optional)
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER", "")
RECIPIENT_PHONE = os.getenv("RECIPIENT_PHONE", "")


def get_ist_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%d-%b-%Y %I:%M %p IST")


def fetch_gold_rate():
    """Scrapes 22K gold rate per gram from Tanishq."""
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
            print(f"Fetching gold rates from: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"Failed with status code: {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text(" ", strip=True)

            # Strategy 1: Look for table rows containing 22K/22 Kt and 1G
            for tr in soup.find_all("tr"):
                row_text = tr.get_text(separator=" ", strip=True)
                if ("22" in row_text) and ("1" in row_text or "1G" in row_text):
                    matches = re.findall(r"₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)", row_text)
                    for m in matches:
                        clean_num = float(m.replace(",", ""))
                        if 5000 <= clean_num <= 30000:
                            return clean_num

            # Strategy 2: Look for 22 Karat / 22 Kt block followed by 1 G price
            pattern_1g = re.search(
                r"22\s*(?:Kt|Karat|K)[\s\S]{1,200}?1\s*G[\s\S]{1,60}?₹?\s*([\d,]{4,7}(?:\.\d{1,2})?)",
                text,
                re.IGNORECASE,
            )
            if pattern_1g:
                val = float(pattern_1g.group(1).replace(",", ""))
                if 5000 <= val <= 30000:
                    return val

            # Strategy 3: Check for 10 Gram 22K rate and calculate per gram
            pattern_10g = re.search(
                r"22\s*(?:Kt|Karat|K)[\s\S]{1,200}?10\s*G[\s\S]{1,60}?₹?\s*([\d,]{5,8}(?:\.\d{1,2})?)",
                text,
                re.IGNORECASE,
            )
            if pattern_10g:
                val_10g = float(pattern_10g.group(1).replace(",", ""))
                per_gram = val_10g / 10.0
                if 5000 <= per_gram <= 30000:
                    return per_gram

        except Exception as e:
            print(f"Error scraping {url}: {e}")

    return None


def send_email(subject, body_html, body_text):
    if not (EMAIL_USER and EMAIL_PASS and RECIPIENT_EMAIL):
        print("Email credentials not provided. Skipping email delivery.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Gold Rate Tracker <{EMAIL_USER}>"
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"Email sent successfully to {RECIPIENT_EMAIL}.")
    except Exception as e:
        print(f"Failed to send email: {e}")


def send_sms(message_body):
    if not (TWILIO_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM and RECIPIENT_PHONE):
        print("Twilio SMS credentials not set. Skipping SMS delivery.")
        return

    try:
        from twilio.rest import Client

        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_FROM,
            to=RECIPIENT_PHONE,
        )
        print(f"SMS sent successfully. Message SID: {message.sid}")
    except Exception as e:
        print(f"Failed to send SMS: {e}")


def main():
    rate = fetch_gold_rate()
    timestamp = get_ist_time()

    if rate is None:
        error_msg = f"Failed to extract Tanishq 22K gold rate on {timestamp}."
        print(error_msg)
        send_email(
            subject="⚠️ [Error] Tanishq Gold Price Check Failed",
            body_html=f"<p>{error_msg}</p><p>Please check site availability or selectors.</p>",
            body_text=error_msg,
        )
        return

    is_drop_alert = rate < THRESHOLD_PRICE
    diff = THRESHOLD_PRICE - rate

    print(f"[{timestamp}] Tanishq 22K Gold Rate: ₹{rate:,.2f}/gram")
    print(f"Threshold: ₹{THRESHOLD_PRICE:,.2f}/gram | Alert Triggered: {is_drop_alert}")

    if is_drop_alert:
        subject = f"🚨 [ALERT] Tanishq 22K Gold Price Dropped to ₹{rate:,.2f}/g!"
        status_label = f"🔥 ALERT: Price is ₹{diff:,.2f}/g BELOW your threshold of ₹{THRESHOLD_PRICE:,.2f}!"
        badge_color = "#e53e3e"
    else:
        subject = f"📊 [Daily Update] Tanishq 22K Gold Rate: ₹{rate:,.2f}/g"
        status_label = f"Price is ₹{abs(diff):,.2f}/g above your alert threshold (₹{THRESHOLD_PRICE:,.2f})."
        badge_color = "#2b6cb0"

    body_text = (
        f"Tanishq 22 Karat Gold Rate Update\n"
        f"Time: {timestamp}\n"
        f"Price per gram: ₹{rate:,.2f}\n"
        f"Status: {status_label}\n"
        f"Source: https://www.tanishq.co.in/gold-rate.html?lang=en_IN\n"
    )

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f7fafc; padding: 20px; }}
        .card {{ max-width: 500px; margin: auto; background: white; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
        .header {{ background-color: {badge_color}; color: white; padding: 18px 24px; font-size: 18px; font-weight: bold; }}
        .content {{ padding: 24px; }}
        .price {{ font-size: 32px; font-weight: bold; color: #1a202c; margin: 12px 0; }}
        .info {{ color: #4a5568; line-height: 1.6; font-size: 14px; }}
        .highlight {{ padding: 10px 14px; background-color: #edf2f7; border-left: 4px solid {badge_color}; border-radius: 4px; margin-top: 16px; font-weight: 500; }}
        .footer {{ padding: 14px 24px; background: #f8fafc; border-top: 1px solid #edf2f7; font-size: 12px; color: #a0aec0; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">{'🚨 Price Drop Alert' if is_drop_alert else 'Daily Gold Rate Update'}</div>
        <div class="content">
          <div class="info">Tanishq • 22 Karat Gold (Per Gram)</div>
          <div class="price">₹{rate:,.2f}</div>
          <div class="info"><strong>Checked At:</strong> {timestamp}</div>
          <div class="highlight">{status_label}</div>
        </div>
        <div class="footer">Automated by GitHub Actions • Tanishq Live Tracker</div>
      </div>
    </body>
    </html>
    """

    sms_text = (
        f"{'🚨 GOLD DROP ALERT!' if is_drop_alert else 'Tanishq Daily Gold Rate'}\n"
        f"22K: ₹{rate:,.2f}/g (at {timestamp}).\n"
        f"{status_label}"
    )

    # Deliver notification if price drops OR if daily summary is requested
    if is_drop_alert or ALWAYS_NOTIFY:
        send_email(subject, body_html, body_text)
        send_sms(sms_text)
    else:
        print("Price is above threshold and ALWAYS_NOTIFY is false. No message sent.")


if __name__ == "__main__":
    main()