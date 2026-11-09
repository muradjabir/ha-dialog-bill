# Dialog Bill & Broadband (Sri Lanka) - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/default)
[![GitHub release](https://img.shields.io/github/v/release/muradjabir/ha-dialog-bill?style=for-the-badge)](https://github.com/muradjabir/ha-dialog-bill/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

Track your **Dialog Axiata** bill balances, invoices, payment history, and broadband data usage directly in Home Assistant.

This custom component communicates with the official [MyDialog Web & Dialog ID](https://dialog.lk/mydialog-web) portal backend to automatically discover and monitor **all connections and services** linked under your Dialog ID profile.

---

## Features

- **Multi-Connection Auto-Discovery:** Automatically discovers and tracks all connections linked to your Dialog profile:
  - **Mobile Connections:** Postpaid and Prepaid GSM SIMs.
  - **Home Broadband:** 4G / 5G Home WiFi routers (HBB).
  - **Dialog Television:** DTV satellite/cable connections.
- **Dedicated Device per Connection:** Each service is represented as an individual device in Home Assistant, grouping its respective billing and data sensors.
- **Connection-Aware Sensors (Postpaid vs. Prepaid):**
  - **Postpaid Connections:**
    - `Outstanding Balance` (in `LKR`, `monetary` device class, `total` state class)
    - `Current Usage` (unbilled usage in `LKR`)
    - `Last Bill Amount` (in `LKR`)
    - `Last Payment Amount` (in `LKR`)
    - `Payment Due Date` (as a `date` entity)
    - `Last Bill Date` (as a `date` entity)
    - `Last Payment Date` (as a `date` entity)
  - **Prepaid Connections:**
    - `Prepaid Balance` (remaining reload credit in `LKR`)
    - `Balance Expiry Date` (credit validity date as a `date` entity)
  - **Common Sensors (All Connections):**
    - `Data Remaining` (in `GB`, `data_size` device class)
    - `Package` (active base tariff plan, e.g. `MY PLAN 360`, `1 FOR 1`)
    - `Connection Status` (e.g. `Connected`, `Active`)
- **Sliding Session Renewal & Persistence:** Uses Dialog's 23-day sliding session token window. Every periodic update automatically renews the sliding session on Dialog's servers and dynamically persists the refreshed credentials in Home Assistant, preventing tokens from expiring and avoiding repetitive OTP verification requests.
- **Seamless 2-Step OTP Authentication:** Log in directly from the Home Assistant UI by entering your mobile number and confirming the SMS OTP. Manual session cookie fallback is also supported.

---

## Installation

### Method 1: Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=muradjabir&repository=ha-dialog-bill&category=integration)

1. In Home Assistant, open **HACS** > **Integrations**.
2. Click the **three dots** in the top-right corner and select **Custom repositories**.
3. Add the repository URL:
   ```text
   https://github.com/muradjabir/ha-dialog-bill
   ```
4. Select Category: **Integration** and click **Add**.
5. Search for **Dialog Bill & Broadband (Sri Lanka)** and click **Download**.
6. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the latest release archive or clone this repository.
2. Copy the `custom_components/dialog_bill` directory into your Home Assistant `<config_dir>/custom_components/` folder.
3. Restart Home Assistant.

---

## Creating a Dialog ID & Linking Connections

If you have multiple Dialog connections (Mobile, Home Broadband, DTV) and want to view them all together:

1. **Create or Log into Dialog ID:**
   - Visit [dialog.lk](https://www.dialog.lk/) or download the **MyDialog App**.
   - Sign up with your primary Dialog mobile number (e.g., `0771369338`) or email address.
   - Enter the 6-digit SMS verification code to verify your profile.
2. **Link Your Connections in Manage Connections:**
   - Open [dialog.lk/mydialog-web/manage-connections](https://www.dialog.lk/mydialog-web/manage-connections).
   - Click **Add Connections**.
   - Dialog can automatically list all numbers registered under your National Identity Card (NIC), or you can manually enter each connection:
     - **Mobile SIM numbers**
     - **Home Broadband numbers** (printed on your router or SIM)
     - **Dialog Television Account numbers**
   - Confirm with the verification OTP sent to each device. All linked connections will now appear under your unified MyDialog profile.
3. **Connect to Home Assistant:**
   - In Home Assistant, go to **Settings** > **Devices & Services** > **Add Integration**.
   - Search for **Dialog Bill & Broadband (Sri Lanka)**.
   - Enter your primary Dialog mobile number (`0771369338`).
   - Enter the 6-digit SMS verification OTP sent to your phone.
   - Select the connections you wish to monitor. Home Assistant will create a dedicated device for each connection.

---

## Configuration

1. In Home Assistant, navigate to **Settings** > **Devices & Services**.
2. Click **Add Integration** in the bottom-right corner.
3. Search for **Dialog Bill & Broadband (Sri Lanka)**.
4. Choose authentication method:
   - **SMS OTP Login (Recommended):** Enter your Dialog mobile number, click Submit, and enter the SMS OTP received.
   - **Direct Session Cookie:** Paste the `SSESS...` session cookie from your browser if desired.
5. If you have multiple connections, select the ones you want to monitor.
6. A dedicated device will be created for each connection with all its billing and broadband sensors.

---

## Example Automation: Bill Due Reminder

Get a push notification when your Dialog bill is due within 3 days:

```yaml
alias: "Dialog Bill Due Reminder"
description: "Send notification when Dialog bill payment due date is approaching"
trigger:
  - platform: time
    at: "09:00:00"
condition:
  - condition: template
    value_template: >-
      {% set due = states('sensor.dialog_0771369338_payment_due_date') %}
      {% if due not in ['unknown', 'unavailable'] %}
        {% set days = ((as_datetime(due) - now()).days) %}
        {{ 0 <= days <= 3 }}
      {% else %}
        false
      {% endif %}
action:
  - action: notify.persistent_notification
    data:
      title: "Dialog Bill Payment Due"
      message: >-
        Your Dialog bill of LKR {{ states('sensor.dialog_0771369338_outstanding_balance') }}
        is due on {{ states('sensor.dialog_0771369338_payment_due_date') }}.
```

---

## Troubleshooting & Token Refresh

- **Token Expiry Prevention:** The integration uses a sliding session mechanism (`Max-Age: 2,000,000` seconds / ~23 days) where every scheduled poll automatically renews the session window on Dialog's servers and dynamically updates Home Assistant's secure storage.
- **Session Re-Authentication:** If Dialog invalidates the session server-side (e.g. after a nationwide maintenance reset), Home Assistant will prompt you to enter a single SMS OTP via the standard UI re-auth prompt without deleting your entities or history.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

