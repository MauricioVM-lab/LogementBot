#!/usr/bin/env python3
"""
CROUS housing watcher
=====================

Polls a search page on trouverunlogement.lescrous.fr and sends a Telegram
alert as soon as at least one accommodation becomes available.

Required environment variables:
    CROUS_URL          Full search URL, including your own filters
    TELEGRAM_TOKEN     Bot token issued by @BotFather
    TELEGRAM_CHAT_ID   Numeric id of your conversation with the bot

Exit codes:
    0  normal run (whether or not something was found)
    1  configuration error, or the site could not be reached
"""

import os
import re
import sys
import time

import requests

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_URL = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=1.3003956_43.718708_1.5653795_43.482654&locationName=Toulouse"
)

URL = os.environ.get("CROUS_URL", DEFAULT_URL)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Identify ourselves honestly: this is a personal watcher, not a scraper.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
        "(personal-housing-watcher)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

MAX_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds


# --------------------------------------------------------------------------
# Fetching and parsing
# --------------------------------------------------------------------------

def fetch_page(url: str) -> str:
    """Download the page, retrying a few times on transient network errors."""
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.text
        except requests.RequestException as error:
            last_error = error
            print(f"Attempt {attempt}/{MAX_ATTEMPTS} failed: {error}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"Could not reach the site: {last_error}")


def count_listings(html: str) -> int:
    """
    Return the number of listings shown on the page.

     0  -> the page explicitly states that nothing is available
    >0  -> number of listings found
    -1  -> unexpected layout, the site may have changed its wording
    """
    if "Aucun logement trouvé" in html:
        return 0

    match = re.search(r"(\d+)\s+logements?\s+trouvés?", html, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))

    return -1


# --------------------------------------------------------------------------
# Notification
# --------------------------------------------------------------------------

def send_telegram(message: str) -> None:
    """Push a message through the Telegram Bot API."""
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set.")

    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    response = requests.post(
        api,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        },
        timeout=20,
    )
    response.raise_for_status()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> int:
    try:
        html = fetch_page(URL)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    count = count_listings(html)

    if count == 0:
        print("Nothing available.")
        return 0

    if count == -1:
        # The site probably changed its wording. Better to raise a false alarm
        # than to fail silently and miss an opening.
        message = (
            "<b>CROUS watcher: unexpected page layout</b>\n\n"
            "The script no longer recognises the page format. "
            "Check manually, and adapt the script if needed.\n\n"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print("Unexpected layout.")
    else:
        plural = "s" if count > 1 else ""
        message = (
            f"<b>{count} logement{plural} CROUS disponible{plural} !</b>\n\n"
            "Connecte-toi immediatement et reserve. "
            "Prevois les 70 EUR de frais de reservation.\n\n"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print(f"{count} listing(s) found, alert sent.")

    try:
        send_telegram(message)
    except Exception as error:  # noqa: BLE001
        print(f"Telegram delivery failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
