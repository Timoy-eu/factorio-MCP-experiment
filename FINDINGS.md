# Erkenntnisse aus den Referenz-Repos

Analysiert wurden (alle geklont, Stand Oktober 2026): Factorio Learning Environment (FLE, MIT),
lveillard/factorio-ai-companion (MIT), thedemon117/ai-player-v3 (MIT laut README),
phiresky/factorio-mcp (ISC laut package.json), JackHopkins/claude-code-plays-factorio (nur Prompt).
Es wurde kein Code kopiert, nur Muster übernommen und neu geschrieben.

## 1. RCON-Anbindung (phiresky/factorio-mcp)

- Factorio ignoriert den Valve-Trick "leeres RESPONSE_VALUE-Paket spiegeln". Für mehrteilige
  Antworten muss nach dem eigentlichen Befehl ein echter Folgebefehl (`rcon.print("")`) als
  Grenze geschickt werden. Alles bis zur Antwort auf die Grenze gehört zur ersten Antwort.
- Lua-Argumente müssen sauber escaped werden (Tagged-Template-Ansatz), sonst bricht
  Spielername/Itemname mit Anführungszeichen den Befehl.
- Ein RCON-Socket ist nicht thread-sicher: alle Aufrufe hinter einem Lock serialisieren
  (ai-player-v3 macht das ebenso).
- Kritisch: `/silent-command` mit Riesen-Lua pro Aufruf stößt an Paketgrenzen. Besser ein
  kleines Mod mit `remote.add_interface` und kurzen Aufrufen (`remote.call(...)`), wie es die
  Companion-Variante mit `/fac_api` macht.

## 2. Rotation und Platzierung (Ursache der FLE-Probleme)

- FLE rechnet intern zwischen eigener Direction-Enum, 8er-Richtungen (Factorio 1.x) und
  16er-Richtungen (Factorio 2.0: 0, 4, 8, 12) um. In `place_entity/server.lua` stehen noch
  Kommentare wie "0 -> 4" aus der 1.x-Zeit neben Mappings, die inzwischen Identität sind.
  Diese Mischung ist eine plausible Fehlerquelle (meine Einschätzung, nicht bestätigt).
- Assembler lassen sich in 2.0 ohne Fluid-Rezept nicht per `rotate()` drehen. FLE löst das mit
  Zerstören und Neuerzeugen (Rezept, Inventar, Gesundheit sichern). Das Muster ist nötig.
- `set_recipe` kann die Richtung verändern. Danach Richtung erneut erzwingen und zurücklesen.
- FLE prüft nach dem Drehen, ob `entity.direction` wirklich dem Ziel entspricht, und wirft sonst
  einen Fehler. Dieses Rücklesen ist das wichtigste robuste Muster.

## 3. Orientierung lösen lassen statt vom Modell raten (Companion)

- Der Schritt `pick_orientation` probiert alle vier Seiten durch, prüft pro Seite mit
  `can_place_entity` (Hauptobjekt und Nachbar) und nimmt die erste gültige. Das Modell muss
  keine Richtung angeben. Genau das braucht ein kleines lokales Modell.
- `find_patch` prüft zusätzlich, ob der Bohrer-Footprint wirklich auf dem Erz liegt.
- `ensure_item` beschafft fehlende Materialien automatisch (rekursives Craften/Sammeln).

## 4. Tool-Zuschnitt für kleine Modelle

- Companion bietet 70 Tools. Für kleine Modelle viel zu viel. FLE verlangt Python-Code vom
  Modell, ebenfalls zu viel.
- Gut übernehmbar: asynchrone Jobs mit `*_status`-Abfrage, begrenzte Welt-Snapshots
  (`world_observe`), Blueprint-Tools, eine Hilfe-Funktion.
- Eigener Ansatz: etwa 12 Tools auf hoher Ebene, kompakte Textausgaben, Fehlermeldungen mit
  Handlungsvorschlag, `status` liefert zusätzlich einen empfohlenen nächsten Schritt.

## 5. Lizenzen

Alle verwendeten Quellen sind permissiv (MIT/ISC). Trotzdem wurde nur das Muster übernommen.
