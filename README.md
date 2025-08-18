# Web Status Monitor — Vendors Status to Telegram & Microsoft Teams

Monitor vendor status pages on a schedule and push compact notifications to **Telegram** and **Microsoft Teams**.

## ✅ What it does

- Scrapes official status pages with **headless Chrome (Selenium)** + **BeautifulSoup**.
- Normalizes and summarizes **today’s status/incidents** per vendor.
- Sends a single, readable notification to **Telegram** and **Teams**.
- Robust to slow/JS-heavy pages and minor DOM changes.

## 🧰 Supported vendors & behavior

| Vendor | What we report | Notes |
|---|---|---|
| **Netskope** | Open incidents + *Past Incidents (Previous 15 days)* | Fix: no false “active” when already **Resolved**. Start time from **Investigating**, end time from **Resolved** when present. |
| **Proofpoint** | “Current Incidents” page | Very simple: typically “No current identified incidents”. |
| **Qualys** | Monthly **History** with filters | Only **non-[Scheduled]** items. Timestamps parsed and **converted to UTC**. |
| **Aruba** | **Today’s** incidents + overall regions | Report non-operational regions; messages stay in **English** (no auto-translation). |
| **Imperva** | Non-operational components (+ affected **POPs**), **Incidents today** | Always shows *Overall status*. Hides the “— 0 incident(s)” wording; still prints **Incidents today**. |
| **CyberArk** | “All Systems Operational” banner + **Incidents today** | Clean layout; hides the “— 0 incident(s)” wording. |
| **Trend Micro** (Cloud One & Vision One) | **Incidents today** per console | One **combined** notification with two sections. Parses `sspDataInfo`, filters by **product**, converts times to **UTC**, and is resilient to JSON quirks. Always notifies (even if “No incidents…”). |
| **Akamai (Guardicore)** | Compact **Component status** by groups + **Incidents today** | If a group’s children are all Operational → single line `Group Operational`. If any child is non-operational → list only those children with state. Shows latest update of any incident today. Timeouts handled; short error messages for Telegram. |

> All messages are compact and consistent: we avoid redundant “— 0 incident(s)” strings but keep “**Incidents today**” header for clarity.

---

## 🗂️ Project structure

```
.
├─ common/
│  ├─ browser.py        # Selenium bootstrap (headless Chrome options)
│  └─ notify.py         # send_telegram() / send_teams()
├─ vendors/
│  ├─ netskope.py
│  ├─ proofpoint.py
│  ├─ qualys.py
│  ├─ aruba.py
│  ├─ imperva.py
│  ├─ cyberark.py
│  ├─ trendmicro.py     # Combined Trend Cloud One + Vision One
│  └─ guardicore.py     # Akamai status
├─ run_vendor.py         # Orchestrator: python run_vendor.py --vendor <name>
└─ .github/workflows/status-check.yml
```

---

## 🔐 Secrets / Environment

Add these **repository secrets** in GitHub:

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `TELEGRAM_USER_ID`   | Telegram chat_id (user or group) |
| `TEAMS_WEBHOOK_URL`  | Microsoft Teams incoming webhook URL |

Optional (debugging):
- `SAVE_HTML`: `1` to save the page source (`*_page_source.html`) for a vendor run. **Default is disabled**.

> We’ve trimmed error messages sent to Telegram to avoid HTTP 400 due to size limits.

---

## ⏱️ Schedule (Europe/Madrid at 08:30 daily)

GitHub Actions CRON runs in **UTC**. To trigger **every day at 08:30 Europe/Madrid**, we include **two** cron rules (summer/winter DST):

```yaml
on:
  workflow_dispatch:
  schedule:
    # CEST (UTC+2) — approx. Mar–Oct
    - cron: '30 6 * * *'
    # CET (UTC+1) — approx. Oct–Mar
    - cron: '30 7 * * *'
```

---

## 🏃 GitHub Actions workflow

**.github/workflows/status-check.yml**

```yaml
name: Web Status Monitor

on:
  workflow_dispatch:
  schedule:
    - cron: '30 6 * * *'  # 08:30 CEST (Madrid)
    - cron: '30 7 * * *'  # 08:30 CET (Madrid)

jobs:
  status_check:
    runs-on: ubuntu-latest

    strategy:
      fail-fast: false
      matrix:
        vendor: [netskope, proofpoint, qualys, aruba, imperva, cyberark, trendmicro, guardicore]

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Install Chromium & chromedriver
        run: |
          sudo apt-get update
          sudo apt-get install -y chromium-browser chromium-chromedriver
          sudo ln -sf /usr/lib/chromium-browser/chromedriver /usr/local/bin/chromedriver

      - name: Run ${{ matrix.vendor }}
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_USER_ID:   ${{ secrets.TELEGRAM_USER_ID }}
          TEAMS_WEBHOOK_URL:  ${{ secrets.TEAMS_WEBHOOK_URL }}
          # SAVE_HTML: "1"   # enable temporarily only if you need to debug DOM
        run: python run_vendor.py --vendor ${{ matrix.vendor }}
```

---

## 📦 Requirements

`requirements.txt`

```
selenium==4.20.0
requests
beautifulsoup4
python-dateutil
```

---

## ▶️ Run locally

```bash
# 1) Set your env
export TELEGRAM_BOT_TOKEN=xxxxx
export TELEGRAM_USER_ID=xxxxx
export TEAMS_WEBHOOK_URL=xxxxx

# 2) Choose a vendor
python run_vendor.py --vendor netskope
python run_vendor.py --vendor proofpoint
python run_vendor.py --vendor qualys
python run_vendor.py --vendor aruba
python run_vendor.py --vendor imperva
python run_vendor.py --vendor cyberark
python run_vendor.py --vendor trendmicro
python run_vendor.py --vendor guardicore
```

> Valid choices are enforced in `run_vendor.py` via a central **REGISTRY**.

---

## 🧪 Notes per vendor (key parsing rules)

- **Netskope**: Selenium + BS. Captures **Open Incidents** and **Past Incidents (Previous 15 Days)**. For each incident, build start time from **Investigating** and end time from **Resolved** when present. Avoids mislabeling past resolved as active.
- **Proofpoint**: Current page only. Treat it as a binary banner (“No current identified incidents”).
- **Qualys**: The history is grouped by months; we **skip any title starting with `[Scheduled]`** and show only unscheduled incidents. Times normalized to **UTC**.
- **Aruba**: Display **today’s** banner (e.g., “No incidents reported today.”). If all regions are **Operational**, say so explicitly; otherwise list the non-operational ones. Keep message language as it appears on the page.
- **Imperva**: List **only non-operational** components; attempt to extract impacted **POPs**. “Incidents today” covers only today’s block (no previous day). Adds an **Overall status** line when everything is green + no incidents.
- **CyberArk**: Pull the top banner (“All Systems Operational”, if present) and the **Incidents today** block. No duplication of dates; if there are 0 incidents, omit the “— 0 incident(s)” pattern.
- **Trend Micro**: Parse the embedded `sspDataInfo` array, **filter by `productEnName`** (Cloud One vs Vision One), group updates by `id`, take only **today’s** updates and **latest status** (e.g. *Resolved*) with **HH:MM UTC**. JSON arrays that are malformed are safely skipped. **Combined** notification with sections `[Trend Cloud One]` and `[Trend Vision One]`, always sent.
- **Akamai (Guardicore)**: Output is **compact**. For each group: if all children are Operational, print a single line `Group Operational`. If any child is not Operational, print the group title followed by children with their states (e.g., `Akamai Control Center Degraded`). “Incidents today” always shown; the latest incident update is used when present. Page load timeouts are handled by stopping the renderer and continuing with partial DOM if needed.

---

## 🧯 Troubleshooting

- **Page too heavy / Timeout**: Vendors like Akamai are JS-heavy. We set a **page load timeout** and, on timeout, run `window.stop()`; the partial DOM is often enough for our parsers.
- **Telegram 400 (message too long)**: Error messages are **shortened** before sending. Your regular notifications are compact by design.
- **DOM changes**: Enable `SAVE_HTML=1` temporarily, rerun the vendor, and open the saved `*_page_source.html` to tweak the parser for the exact DOM.

---

## 📝 Changelog (latest)

- Split architecture into **vendor modules** + **orchestrator** `run_vendor.py`.
- **Netskope**: fixed Past Incidents parsing and state derivation; better titles & times.
- **Proofpoint**: minimal banner detection.
- **Qualys**: ignore `[Scheduled]`; convert times to **UTC**; add link capture.
- **Aruba**: clean banner + region checks; don’t translate English content.
- **Imperva**: compact style, **Overall status**, today-only incidents; POP extraction; hide “— 0 incident(s)”.
- **CyberArk**: no date duplication; hide “— 0 incident(s)”.
- **Trend Micro**: **combined** Cloud One + Vision One, parse `sspDataInfo`, filter by product, handle JSON quirks, **always notify**.
- **Akamai (Guardicore)**: compact grouping, list only non-operational children; latest incident update; timeout resilience; short error texts.
- **Schedule**: run **daily at 08:30 Europe/Madrid** via dual cron (CET/CEST).
- **Debug**: `SAVE_HTML` disabled by default (enable only when needed).

---

## License

MIT (see `LICENSE`).