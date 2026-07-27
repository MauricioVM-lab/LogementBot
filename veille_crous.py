#!/usr/bin/env python3
"""
Veille CROUS
============

Surveille une page de recherche de trouverunlogement.lescrous.fr et envoie
une alerte Telegram dès qu'au moins un logement devient disponible.

Variables d'environnement attendues :
    CROUS_URL          URL complète de ta recherche (avec tes filtres)
    TELEGRAM_TOKEN     jeton du bot fourni par @BotFather
    TELEGRAM_CHAT_ID   identifiant de ta conversation avec le bot

Codes de sortie :
    0  exécution normale (logement trouvé ou non)
    1  erreur de configuration ou d'accès au site
"""

import os
import re
import sys
import time

import requests

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

URL_PAR_DEFAUT = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=1.3003956_43.718708_1.5653795_43.482654&locationName=Toulouse"
)

URL = os.environ.get("CROUS_URL", URL_PAR_DEFAUT)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# On s'annonce honnêtement : c'est une veille personnelle, pas un scraper agressif.
ENTETES = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
        "(veille-logement-personnelle)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

NB_TENTATIVES = 3
DELAI_ENTRE_TENTATIVES = 5  # secondes


# --------------------------------------------------------------------------
# Récupération et analyse de la page
# --------------------------------------------------------------------------

def recuperer_page(url: str) -> str:
    """Télécharge la page, avec quelques tentatives en cas d'incident réseau."""
    derniere_erreur = None

    for tentative in range(1, NB_TENTATIVES + 1):
        try:
            reponse = requests.get(url, headers=ENTETES, timeout=20)
            reponse.raise_for_status()
            return reponse.text
        except requests.RequestException as erreur:
            derniere_erreur = erreur
            print(f"Tentative {tentative}/{NB_TENTATIVES} échouée : {erreur}")
            if tentative < NB_TENTATIVES:
                time.sleep(DELAI_ENTRE_TENTATIVES)

    raise RuntimeError(f"Impossible de joindre le site : {derniere_erreur}")


def compter_logements(html: str) -> int:
    """
    Retourne le nombre de logements affichés.

     0  -> la page annonce explicitement qu'il n'y a rien
    >0  -> nombre de logements trouvés
    -1  -> structure inattendue (le site a peut-être changé)
    """
    if "Aucun logement trouvé" in html:
        return 0

    correspondance = re.search(
        r"(\d+)\s+logements?\s+trouvés?", html, flags=re.IGNORECASE
    )
    if correspondance:
        return int(correspondance.group(1))

    return -1


# --------------------------------------------------------------------------
# Notification
# --------------------------------------------------------------------------

def envoyer_telegram(message: str) -> None:
    """Envoie un message via l'API Telegram."""
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_TOKEN et TELEGRAM_CHAT_ID doivent être définis."
        )

    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    reponse = requests.post(
        api,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        },
        timeout=20,
    )
    reponse.raise_for_status()


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

def main() -> int:
    try:
        html = recuperer_page(URL)
    except RuntimeError as erreur:
        print(erreur, file=sys.stderr)
        return 1

    nombre = compter_logements(html)

    if nombre == 0:
        print("Rien de disponible.")
        return 0

    if nombre == -1:
        # Le site a probablement changé de formulation : mieux vaut prévenir
        # que rater une occasion en silence.
        message = (
            "⚠️ <b>Veille CROUS : structure de page inattendue</b>\n\n"
            "Le script ne reconnaît plus le format de la page. "
            "Vérifie manuellement, et adapte le script si besoin.\n\n"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print("Structure inattendue.")
    else:
        pluriel = "s" if nombre > 1 else ""
        message = (
            f"🚨 <b>{nombre} logement{pluriel} CROUS disponible{pluriel} !</b>\n\n"
            "Connecte-toi immédiatement et réserve. "
            "Prévois les 70 € de frais de réservation.\n\n"
            f'<a href="{URL}">Ouvrir la recherche</a>'
        )
        print(f"{nombre} logement(s) trouvé(s) — alerte envoyée.")

    try:
        envoyer_telegram(message)
    except Exception as erreur:  # noqa: BLE001
        print(f"Échec de l'envoi Telegram : {erreur}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
