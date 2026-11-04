# Wizz Route Explorer – Render Free

Diese Flask-Webseite liest die öffentlich zugängliche Wizz-Air-All-You-Can-Fly-PDF-Streckenliste serverseitig aus und berechnet mögliche Streckenketten mit bis zu drei Zwischenstopps. Keine API-Schlüssel erforderlich.

## Kostenlos auf Render veröffentlichen

1. Entpacke das ZIP und lade **den Inhalt des Ordners** `wizz-live` in ein neues öffentliches oder privates GitHub-Repository (Dateien `app.py`, `requirements.txt`, `render.yaml` und Ordner `templates`).
2. Melde dich auf https://dashboard.render.com an und verbinde GitHub.
3. Wähle **New > Blueprint** und das Repository. Render liest `render.yaml` automatisch.
4. Prüfe, dass **Free** ausgewählt ist, und bestätige **Deploy**. Falls Render in deiner Region oder für deinen Account keinen kostenlosen Web Service anbietet, nicht versehentlich einen kostenpflichtigen Tarif bestätigen.
5. Nach erfolgreichem Deployment zeigt Render eine Adresse wie `https://wizz-route-explorer-xxxx.onrender.com` an. Das ist deine Webseite, ohne eigene Domain.
6. Öffne die Adresse auf dem Handy. Beim ersten Aufruf nach einer Pause kann die kostenlose Instanz etwas brauchen, um aufzuwachen.

## Technische Hinweise

- Start: `gunicorn --bind 0.0.0.0:$PORT app:app`.
- Healthcheck `/health`; Streckendaten `/api/routes`.
- Datenquelle: https://multipass.wizzair.com/aycf-availability.pdf ; Cache eine Stunde pro laufender Instanz.
- Die Webseite kann nur theoretische Streckenketten anzeigen, **keine konkreten Flüge, Uhrzeiten, Umsteigegarantie oder garantierten All-You-Can-Fly-Sitze**. Das PDF kann zeitweise nicht erreichbar sein oder sein Format ändern. Die Datenquelle kann sich ändern oder gesperrt werden.
- Das 72-Stunden-Buchungsfenster wird **nicht anhand einzelner Flüge validiert**, weil die PDF keine individuellen Abflugzeiten liefert. Jede Strecke vor Buchung im Wizz-Air-Portal prüfen.
- Render Free kann schlafen, Limits haben und sich ändern. Prüfe die aktuellen Bedingungen vor Aktivierung.

## Lokal

`pip install -r requirements.txt` und `python app.py`; danach http://localhost:5000 öffnen.
