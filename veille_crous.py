#!/usr/bin/env python3
"""
CROUS housing watcher
=====================

Polls a search page on trouverunlogement.lescrous.fr and sends an email
alert as soon as at least one accommodation becomes available.

Required environment variables:
    CROUS_URL          Full search URL, including your own filters
    SMTP_USER          Sender mailbox address (e.g. a Gmail address)
    SMTP_PASSWORD      SMTP password or app password for that mailbox

Optional:
    SMTP_HOST          SMTP server (default: smtp.gmail.com)
    SMTP_PORT          SMTP port, implicit TLS (default: 465)
    MAIL_TO            Recipient address (default: ferwizz46@gmail.com)
    DIAGNOSE=1         Print a diagnostic report instead of sending alerts.
                       The report contains no secrets and is safe to share.

Exit codes:
    0  normal run (whether or not something was found)
    1  configuration error, or the site could not be reached
"""

import os
import re
import smtplib
import sys
import time
import unicodedata
from email.mime.text import MIMEText

import requests

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_URL = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=4.7718134_45.8082628_4.8983774_45.7073666&locationName=Lyon"
)

URL = os.environ.get("CROUS_URL", DEFAULT_URL)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
MAIL_TO = os.environ.get("MAIL_TO", "ferwizz46@gmail.com")
DIAGNOSE = os.environ.get("DIAGNOSE") == "1"

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

# Each listing on the results page links to a detail page under this path.
# Counting those links is our accent-proof fallback.
LISTING_LINK = re.compile(r"/tools/\d+/accommodations/(\d+)")


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def strip_accents(text: str) -> str:
    """
    Lowercase the text and remove every diacritic.

    This makes pattern matching immune to encoding accidents: whether the
    page decodes as "trouve", "trouve" with an acute accent, or the mojibake
    "trouvA(c)", the normalised form is always the same.
    """
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return without_marks.lower()


# --------------------------------------------------------------------------
# Fetching and parsing
# --------------------------------------------------------------------------

def fetch_page(url: str) -> requests.Response:
    """Download the page, retrying a few times on transient network errors."""
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()

            # Do not trust the default fallback. When the server omits the
            # charset, requests assumes ISO-8859-1 and mangles every accent.
            if not response.encoding or response.encoding.lower() in (
                "iso-8859-1",
                "latin-1",
            ):
                response.encoding = response.apparent_encoding or "utf-8"

            return response
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

    Three independent strategies are tried in order, so a wording change on
    the site does not silently break the watcher.
    """
    flat = strip_accents(html)

    # Strategy 1: the explicit "nothing found" banner. We deliberately stop
    # the pattern before the accented character, so the match survives even
    # a badly decoded page.
    if "aucun logement trouv" in flat:
        return 0

    # Strategy 2: the results counter, e.g. "20 logements trouves en France".
    match = re.search(r"(\d+)\s+logements?\s+trouv", flat)
    if match:
        return int(match.group(1))

    # Strategy 3: count distinct links to listing detail pages.
    identifiers = set(LISTING_LINK.findall(html))
    if identifiers:
        return len(identifiers)

    return -1


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

def diagnose(response: requests.Response) -> None:
    """Print a secret-free report describing what the site actually returned."""
    html = response.text
    flat = strip_accents(html)

    title = re.search(r"<title>(.*?)</title>", html, flags=re.S | re.I)

    print("=" * 62)
    print("DIAGNOSTIC REPORT")
    print("=" * 62)
    print(f"HTTP status        : {response.status_code}")
    print(f"Final URL path     : {response.url.split('?')[0]}")
    print(f"Redirected         : {len(response.history) > 0}")
    print(f"Declared encoding  : {response.encoding}")
    print(f"Detected encoding  : {response.apparent_encoding}")
    print(f"Body length        : {len(html)} characters")
    print(f"Page title         : {title.group(1).strip()[:90] if title else 'NONE'}")
    print("-" * 62)
    print(f"'aucun logement trouv' present  : {'aucun logement trouv' in flat}")
    print(f"'logements trouv' present       : {'logements trouv' in flat}")
    print(f"listing links found             : {len(set(LISTING_LINK.findall(html)))}")
    print(f"looks like a login page         : {'identification' in flat[:4000]}")
    print(f"count_listings() returns        : {count_listings(html)}")
    print("-" * 62)
    print("First 400 characters of the body:")
    print(html[:400].replace("\n", " "))
    print("=" * 62)


# --------------------------------------------------------------------------
# Notification
# --------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> None:
    """Send an HTML email through SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError("SMTP_USER and SMTP_PASSWORD must be set.")

    message = MIMEText(html_body, "html", "utf-8")
    message["Subject"] = subject
    message["From"] = SMTP_USER
    message["To"] = MAIL_TO

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [MAIL_TO], message.as_string())


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> int:
    try:
        response = fetch_page(URL)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    if DIAGNOSE:
        diagnose(response)
        return 0

    count = count_listings(response.text)

    if count == 0:
        print("Nothing available.")
        return 0

    if count == -1:
        # The site probably changed its wording. Better to raise a false alarm
        # than to fail silently and miss an opening.
        subject = "CROUS watcher: unexpected page layout"
        message = (
            "<b>CROUS watcher: unexpected page layout</b><br><br>"
            "The script no longer recognises the page format. "
            "Check manually, and adapt the script if needed.<br><br>"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print("Unexpected layout.")
    else:
        plural = "s" if count > 1 else ""
        subject = f"{count} logement{plural} CROUS disponible{plural} !"
        message = (
            f"<b>{count} logement{plural} CROUS disponible{plural} !</b><br><br>"
            "Connecte-toi immediatement et reserve. "
            "Prevois les 70 EUR de frais de reservation.<br><br>"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print(f"{count} listing(s) found, alert sent.")

    try:
        send_email(subject, message)
    except Exception as error:  # noqa: BLE001
        print(f"Email delivery failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
