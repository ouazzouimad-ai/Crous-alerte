#!/usr/bin/env python3
"""
Surveillance des logements CROUS disponibles a Paris (phase complementaire)
et envoi d'une notification push (via ntfy.sh) des qu'un nouveau logement apparait.
"""

import json
import os
import time
import re
from pathlib import Path
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright

EMAIL = os.environ.get("CROUS_EMAIL", "TON_EMAIL_ICI")
PASSWORD = os.environ.get("CROUS_PASSWORD", "TON_MOT_DE_PASSE_ICI")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "crousalerte")

NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

VILLE_RECHERCHEE = "Paris"

STATE_FILE = Path(__file__).parent / "seen_logements.json"

LOGIN_URL = "https://messervices.etudiant.gouv.fr/oauth2/login"
LOGEMENT_URL = "https://trouverunlogement.lescrous.fr/tools/37/search?bounds=&academies=&regions=&occupationModes=&residence="


def send_notification(title, message):
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
        print(f"[{datetime.now()}] Notification envoyee : {title}")
    except Exception as e:
        print(f"[{datetime.now()}] Erreur envoi notification : {e}")


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen):
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

    return browser, context, page


def check_logements(page):
    page.goto(LOGEMENT_URL, wait_until="networkidle")
    time.sleep(2)

    try:
        search_input = page.locator('input[placeholder*="ville" i], input[placeholder*="recherch" i]')
        if search_input.count() > 0:
            search_input.first.fill(VILLE_RECHERCHEE)
            page.wait_for_timeout(1500)
    except Exception:
        pass

    cards = page.locator('[class*="card"], [class*="result"], article')
    results = []
    count = cards.count()
    for i in range(count):
        card = cards.nth(i)
        text = card.inner_text().strip()
        if VILLE_RECHERCHEE.lower() in text.lower():
            uid = re.sub(r"\s+", " ", text)[:200]
            results.append({"id": uid, "text": text})

    return results


def run_check():
    seen = load_seen()

    with sync_playwright() as p:
        browser, context, page = login_and_get_page(p)
        try:
            logements = check_logements(page)
        finally:
            browser.close()

    nouveaux = [l for l in logements if l["id"] not in seen]

    if nouveaux:
        for l in nouveaux:
            resume = l["text"][:200]
            send_notification(
                title=f"Nouveau logement CROUS a {VILLE_RECHERCHEE} !",
                message=resume,
            )
            seen.add(l["id"])
        save_seen(seen)
    else:
        print(f"[{datetime.now()}] Aucun nouveau logement a {VILLE_RECHERCHEE}.")


def main():
    print(f"[{datetime.now()}] Verification unique des logements CROUS...")
    run_check()


if __name__ == "__main__":
    main()
