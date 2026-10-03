# Tanishq 22K Gold Rate Tracker (Zero-Secret GitHub Agent)

An automated GitHub Actions agent that tracks the daily **22 Karat gold rate** per gram from Tanishq every day at **12:00 PM IST**.

Uses GitHub's native **Commit/Push Email Notification** hook:
- No Gmail App Passwords, Twilio credentials, or API secrets required.
- At 2:00 PM IST, the action checks Tanishq, records the rate, and pushes a commit to your repository.
- GitHub automatically sends an email to your verified address containing the rate and an alert banner if the price falls below **₹13,750 per gram**.

---

## ⚙️ Required One-Time GitHub Settings

### 1. Enable GitHub Email Notifications
1. On your repo page, go to **Settings** → scroll down to your current **Email notifications** service screen.
2. Under **Address**, input your email address.
3. Check the **Active** checkbox.
4. Click **Save** / **Update service**.

### 2. Grant Workflow Write Permissions
For GitHub Actions to push commits back to your repo:
1. Go to repository **Settings**.
2. In the left sidebar, click **Actions** → **General**.
3. Scroll down to **Workflow permissions**.
4. Select **Read and write permissions**.
5. Click **Save**.
