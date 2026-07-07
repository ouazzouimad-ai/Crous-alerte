#!/usr/bin/env python3
"""
Surveillance des logements CROUS disponibles à Paris (phase complémentaire)
et envoi d'une notification push (via ntfy.sh) dès qu'un nouveau logement apparaît.
Tourne en continu (vérification toutes les 25s) pendant ~5h40, puis le workflow
GitHub Actions relance automatiquement un nouveau cycle.
"""

import json
import os
import time
import re
from pathlib import Path
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

# ================== CONFIGURATION ==================
EMAIL = os.environ.get("CROUS_EMAIL", "TON_EMAIL_ICI")
PASSWORD = os.environ.get("CROUS_PASSWORD", "TON_MOT_DE_PASSE_ICI")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "crousalerte")

NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

VILLE_RECHERCHEE = "Paris"

STATE_FILE = Path(__file__).parent / "seen_logements.json"

LOGIN_URL = "https://messervices.etudiant.gouv.fr/oauth2/login"
LOGEMENT_URL = "https://trouverunlogement.lescrous.fr/tools/37/search?bounds=&academies=&regions=&occupationModes=&residence="
# =====================================================


def send_notification(title: str, message: str):
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "urgent",
                "Tags": "house,rotating_light",
            },
            timeout=10,
        )
        print(f"[{datetime.now()}] Notification envoyée : {title}")
    except Exception as e:
        print(f"[{datetime.now()}] Erreur envoi notification : {e}")


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(list(seen)))


def login_and_get_page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto(LOGIN_URL, wait_until="networkidle")

    try:
        page.click('img[src*="MSEConnect"]', timeout=10000)
    except Exception:
        page.click('a:has-text("MesServices"), button:has-text("MesServices")', timeout=10000)

    page.wait_for_load_state("networkidle")

    page.get_by_label(re.compile("Adresse courriel", re.IGNORECASE)).fill(EMAIL)
    page.get_by_label(re.compile("Mot de passe", re.IGNORECASE)).fill(PASSWORD)

    try:
        page.get_by_text("Je ne suis pas un robot").click(timeout=5000)
    except Exception:
        pass

    page.get_by_role("button", name=re.compile("S'identifier", re.IGNORECASE)).click()
    page.wait_for_load_state("networkidle")

    print(f"[{datetime.now()}] URL après tentative de connexion : {page.url}")

    return browser, context, page


def check_logements(page) -> list[dict]:
    """Va sur la page de recherche et récupère les logements affichés pour Paris."""
    page.goto(LOGEMENT_URL, wait_until="networkidle")
    time.sleep(2)

    print(f"[{datetime.now()}] URL après navigation : {page.url}")
    print(f"[{datetime.now()}] Titre de la page : {page.title()}")

    try:
        search_input = page.locator('input[placeholder*="ville" i], input[placeholder*="recherch" i]')
        if search_input.count() > 0:
            search_input.first.fill(VILLE_RECHERCHEE)
            page.wait_for_timeout(1500)
    except Exception:
        pass

    cards = page.locator('[class*="card"], [class*="result"], article')
    count = cards.count()
    print(f"[{datetime.now()}] Nombre total d'éléments 'card/result/article' trouvés sur la page : {count}")

    results = []
    for i in range(count):
        card = cards.nth(i)
        text = card.inner_text().strip()
        if VILLE_RECHERCHEE.lower() in text.lower():
            uid = re.sub(r"\s+", " ", text)[:200]
            results.append({"id": uid, "text": text})

    print(f"[{datetime.now()}] Nombre d'éléments contenant '{VILLE_RECHERCHEE}' : {len(results)}")

    return results


def run_continuous(max_runtime_seconds: int, check_interval_seconds: int):
    """Se connecte une seule fois, puis vérifie les logements en boucle rapprochée
    jusqu'à ce que max_runtime_seconds soit écoulé (pour rester sous la limite de
    6h par job GitHub Actions)."""
    seen = load_seen()
    start_time = time.time()

    with sync_playwright() as p:
        browser, context, page = login_and_get_page(p)

        try:
            while time.time() - start_time < max_runtime_seconds:
                try:
                    logements = check_logements(page)
                    nouveaux = [l for l in logements if l["id"] not in seen]

                    if nouveaux:
                        for l in nouveaux:
                            resume = l["text"][:200]
                            send_notification(
                                title=f"🏠 Nouveau logement CROUS à {VILLE_RECHERCHEE} !",
                                message=resume,
                            )
                            seen.add(l["id"])
                        save_seen(seen)
                    else:
                        print(f"[{datetime.now()}] Aucun nouveau logement à {VILLE_RECHERCHEE}.")

                except Exception as e:
                    print(f"[{datetime.now()}] Erreur pendant la vérification (on continue) : {e}")
                    try:
                        if "oauth2" in page.url or "login" in page.url.lower():
                            print(f"[{datetime.now()}] Session expirée, reconnexion...")
                            browser.close()
                            browser, context, page = login_and_get_page(p)
                    except Exception as e2:
                        print(f"[{datetime.now()}] Erreur reconnexion : {e2}")

                time.sleep(check_interval_seconds)
        finally:
            browser.close()

    print(f"[{datetime.now()}] Fin du cycle de surveillance (durée max atteinte).")


def main():
    MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_SECONDS", 5 * 3600 + 40 * 60))
    CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", 25))

    print(f"[{datetime.now()}] Démarrage de la surveillance en continu "
          f"(intervalle {CHECK_INTERVAL_SECONDS}s, durée max {MAX_RUNTIME_SECONDS}s)...")
    run_continuous(MAX_RUNTIME_SECONDS, CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
