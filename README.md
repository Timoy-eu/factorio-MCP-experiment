# factorio-agent-mcp

MCP-Server, mit dem auch kleine lokale Modelle Factorio 2.0 spielen können. Statt 70 Low-Level-Tools
gibt es 50 Aktionen auf hoher Ebene (13 Kernaktionen plus FLE-Parität, Karte, Blueprints). Der Server übernimmt Planung, Orientierung und Verifikation,
das Modell muss nur noch die Tools aufrufen. Hintergrund und Quellen: `FINDINGS.md`.

```
Modell <-> MCP-Client <-stdio-> factorio-agent-mcp (Python) <-RCON-> Factorio + Mod fac_agent (Lua)
```

## Wichtig: Teststand

Getestet ist alles gegen einen Mock der Factorio-API (64 Tests, `pytest`): Python, RCON-Protokoll
(inklusive mehrteiliger Antworten), echter Mod-Lua-Code, Orientierungssuche, Rücklesen, rekursives
Craften. Gegen ein echtes Factorio 2.0 wurde noch nichts gelaufen. Rechne mit kleinen Anpassungen
an einzelnen API-Aufrufen (siehe "Bekannte Unsicherheiten").

## Installation

Schritt für Schritt mit OpenCode unter Linux: **`INSTALL_OPENCODE.md`** (mit Beispielen in `examples/`).

Kurzfassung:

1. Mod installieren: `dist/fac_agent_0.2.0.zip` in den Factorio-Ordner `mods/` legen
   (oder den Ordner `mod/fac_agent` kopieren). Der Mod braucht Factorio 2.0.
2. Server mit RCON starten:
   `factorio --start-server meine-karte.zip --rcon-port 27015 --rcon-password geheim`
   (Hinweis: Befehle per `/silent-command` deaktivieren Errungenschaften.)
3. MCP-Server installieren: `pip install -e .` (Python 3.10+, Paket `mcp`).
4. Im MCP-Client eintragen (Beispiel `mcp.example.json`):

```json
{
  "mcpServers": {
    "factorio": {
      "command": "factorio-agent-mcp",
      "env": {
        "FACTORIO_RCON_HOST": "127.0.0.1",
        "FACTORIO_RCON_PORT": "27015",
        "FACTORIO_RCON_PASSWORD": "geheim"
      }
    }
  }
}
```

Das rohe `run_lua`-Tool ist enthalten. Seine Beschreibung sagt dem Modell, dass es nur im absoluten Notfall benutzt werden darf, wenn kein anderes Tool reicht. Mit `FACTORIO_MCP_DISABLE_LUA=1` wird es entfernt.

## Tools

| Tool | Zweck |
|---|---|
| `status` | Position, Inventar, Gebäude mit Status, empfohlene nächste Schritte |
| `look` | Umgebung scannen (Erz, Bäume, Felsen, Wasser, eigene Gebäude, Gegner) |
| `find` | nächstes Erz, Baum, Fels, Wasser oder Gebäude |
| `gather` | von Hand abbauen (Holz, Stein, Kohle, Eisen, Kupfer), Laufweg automatisch |
| `craft` | von Hand herstellen inklusive Zwischenprodukten, `preview` zeigt das Rezept |
| `build` | Gebäude setzen, Richtung `auto` sucht eine funktionierende, Ausweichplatz bei Blockade |
| `rotate` | Gebäude drehen, Ergebnis wird zurückgelesen (Assembler werden neu erzeugt) |
| `build_miner` | Bohrer auf Erz, der direkt in einen Ofen liefert, Seite wird automatisch gesucht |
| `fuel` | Brennstoff einfüllen (eine Stelle oder alle Brenner in 30 Feldern) |
| `collect` | fertige Platten und Ziegel aus Öfen und Maschinen holen |
| `insert` | Items in ein Gebäude stecken |
| `set_recipe` | Assembler-Rezept setzen |
| `research` | Forschung auflisten oder einreihen |

### Erweiterte Tools (FLE-Parität und mehr)

| Tool | Zweck | FLE-Entsprechung |
|---|---|---|
| `can_place` | prüft Platz, nennt Blocker und nächsten freien Ort | `can_place_entity` |
| `nearest_buildable` | nächste freie Fläche, optional auf Erz | `nearest_buildable` |
| `build_next_to` | direkt neben ein Gebäude bauen (Seite, Abstand) | `place_entity_next_to` |
| `pickup` | Gebäude aufnehmen | `pickup_entity` |
| `move_entity` | Gebäude verschieben (mit Rückfall bei Fehler) | `shift_entity` |
| `extract` | Items aus Gebäude nehmen | `extract_item` |
| `inventory` | eigenes Inventar oder das eines Gebäudes | `inspect_inventory` |
| `inspect` | Details: Richtung, Status, Rezept, Inventare, Ausgabeziel, Strom | `get_entity` |
| `list_entities` | Gebäude in der Nähe plus zusammenhängende Band-, Rohr- und Stromnetze | `get_entities` |
| `resource_patch` | Größe, Menge, Mittelpunkt, Bounding Box eines Erzfelds | `get_resource_patch` |
| `move_to` | zu einer Position gehen | `move_to` |
| `connect` | Band, Rohr oder Strommasten verlegen (A* um Hindernisse), `dry_run` zählt Teile | `connect_entities`, `get_connection_amount` |
| `research_info` | Fortschritt und fehlende Forschungspakete | `get_research_progress` |
| `score` | Produktionsstatistik | `score` |
| `launch_rocket` | Rakete starten | `launch_rocket` |
| `say`, `set_game_speed` | Chat-Nachricht, Spielgeschwindigkeit | `send_message`, `sleep` (Ersatz) |
| `craft`, `gather`, `build`, `rotate`, `insert`, `set_recipe`, `research`, `find`, `look` | siehe oben | `craft_item`, `harvest_resource`, `place_entity`, `rotate_entity`, `insert_item`, `set_entity_recipe`, `set_research`, `nearest`, `print` |

Nicht übernommen: das Schreiben von Python-Code durch das Modell (FLE-REPL). Stattdessen gibt es
feste Tools, `run_lua` als letzter Ausweg.

### Selbsttest

`selftest` prüft in einem freien Sandbox-Bereich die Annahmen des Mods über die Factorio-API und räumt danach auf.
Beim ersten Lauf in echtem Factorio ausführen und die `FAIL`-Zeilen melden. Ausführlich in `INSTALL_OPENCODE.md`.

### Spielanleitung für das Modell

Der Server liefert beim Verbinden kurze `instructions` mit (Arbeitsweise, Regeln). Das Tool `guide`
enthält das ausführliche Wissen: Arbeitsmethode, Frühspiel, Bänder und Inserter, Strom, Automatisierung,
Fehlersuche und Tool-Überblick (`guide topic=belts` usw.). Manche lokale Clients ignorieren `instructions`,
deshalb verweist auch `status` im Text darauf und das Modell kann `guide` selbst aufrufen. Den Inhalt
passt du in `src/factorio_agent_mcp/guide.py` an. Für ein lokales Modell lohnt es sich zusätzlich, die
`INSTRUCTIONS` in den System-Prompt des Clients zu kopieren.

### Chat und Batch

| Tool | Zweck |
|---|---|
| `say` | Nachricht als `[Bot]` im Spiel-Chat (hellblau) |
| `read_chat` | liest neue Chat-Zeilen, die Spieler im Spiel getippt haben, so kann der Mensch dem Bot Anweisungen geben |
| `batch` | mehrere Tools in einem Aufruf (`[{"tool":"build","args":{...}}, ...]`), stoppt beim ersten Fehler, höchstens 25 Aktionen |

Erfolgreiche Aktionen (bauen, verlegen, craften, forschen, Blueprint setzen, ...) meldet der Bot automatisch kurz
im Spiel-Chat. `FACTORIO_MCP_CHAT=0` schaltet das ab.

### Karten

| Tool | Zweck |
|---|---|
| `map` | ASCII-Karte für das Modell, beliebige Fläche zwischen zwei Ecken (max. 100x60), Bänder als Pfeile `^ > v <`, Maschinen als Buchstaben, Erz `i c k s`, `t` Baum, `~` Wasser, `@` du. `layers` filtert (`belts,pipes,power,machines,ore,trees,water,enemies`) |
| `render_map` | realistisches SVG für den **Menschen** (Gelände, Erzdichte, Bäume, Maschinen mit Statusring, Bänder mit Laufrichtung, Rohre, Masten mit Kabeln, Legende). Speichert nach `renders/` und startet einen Live-Viewer auf `http://127.0.0.1:8765/` (folgt dem Agenten, Zoom, freie Fläche). `FACTORIO_MCP_VIEWER_PORT=0` schaltet den Viewer ab |

### Items und Maschinen beobachten

| Tool | Zweck |
|---|---|
| `belt_contents` | was liegt auf den Bändern einer Fläche (Items, Füllgrad, leere Stücke), mit Hinweis auf leere oder gestaute Bänder |
| `trace_item` | legt ein Item (am besten Holz) auf ein Band und verfolgt es: Laufzeit, Strecke, "STUCK" mit Ort, oder "hat das Band verlassen". Beweist, dass ein Band verbunden ist und richtig herum läuft |
| `measure_flow` | misst über N Sekunden Spielzeit eine Maschine (Crafts pro Minute, Anteil Arbeitszeit) oder ein Band (mittlere Last); mit `item` die Produktion der ganzen Fabrik pro Minute |
| `machine_stats` | beobachtet alle Maschinen im Umkreis, zeigt Arbeitsanteil und Rate pro Maschine und eine Diagnose (kein Brennstoff, kein Strom, fehlender Input, blockierter Ausgang) |

Die Messung läuft über wiederholte Abfragen (`sample`, `trace_probe`) von Python aus, der Mod braucht
dafür keinen Tick-Handler. Raten werden aus Spiel-Ticks berechnet, nicht aus Echtzeit. Der Durchsatz eines
Bands ist eine Schätzung (mittlere Last), keine exakte Zählung. Gegen echtes Factorio noch ungeprüft:
`LuaTransportLine.insert_at_back`, `get_item_count` auf Bandlinien und `products_finished`.

### Zusammenarbeit Modell und Mensch

| Tool | Zweck |
|---|---|
| `blueprint_save` | Bereich als Blueprint speichern (Datei `factorio-data/blueprints/<name>.json`, von Hand editierbar) |
| `blueprint_list`, `blueprint_show`, `blueprint_note`, `blueprint_delete` | verwalten, als ASCII ansehen (auch gedreht), Notizen und Status `draft/tested` pflegen |
| `blueprint_place` | mit Drehung 0/90/180/270 bauen, `dry_run` prüft Items und freie Plätze, Fehler werden einzeln gemeldet |
| `notes` | persistentes Notizbuch (Ziele, Koordinaten, Lektionen), überlebt Kontextverlust |
| `overview` | Anzahl aller Gebäude und alles, was nicht läuft (kein Brennstoff, kein Strom, ...) |
| `checkpoint` | Spielstand speichern, den der Mensch später laden kann |

Blueprints sind absichtlich nicht vorgefertigt. Das Modell baut etwas, testet es, speichert es,
und ihr verbessert es gemeinsam über Notizen und Status. Der Ordner liegt über
`FACTORIO_MCP_DATA_DIR` (Standard `factorio-data`).

Antworten sind kurze Texte mit Handlungsvorschlag im Fehlerfall, zum Beispiel
`ERR missing: missing 4 iron-plate | try: smelt iron-ore in a furnace (...)`.

## Designentscheidungen für kleine Modelle

- Wenige Tools, klare Namen, kurze Beschreibungen.
- Richtungen löst der Server (`auto`), jede Platzierung und Drehung wird zurückgelesen.
- `status` enthält eine regelbasierte Planung (`src/factorio_agent_mcp/planner.py`), das
  Modell muss keine Build-Order im Kopf haben.
- Fehler nennen Ursache und nächsten Schritt statt nur "failed".
- Bewegung (Teleport) und Abbau (sofort) sind bewusst vereinfacht. Das ist kein "ehrliches"
  Spielen. Wer das ändern will, passt `move_near` und `gather` in `mod/fac_agent/control.lua` an.

## Tests

```
pip install -e ".[test]"
pytest
```

`tests/mock_factorio.lua` ist eine kleine Fake-Welt (Kollisionen, Inventare, Rezepte, Bohrer-Ausgabe).
Sie prüft die Logik des Mods, aber nicht das Verhalten der echten Engine.

## Bekannte Unsicherheiten (bei erstem Lauf in Factorio prüfen)

- `LuaEntity.supports_direction`, `drop_target`, `get_output_inventory` und
  `defines.inventory.crafter_input` sind aus der 2.0-Doku und aus den Referenz-Repos abgeleitet,
  nicht live geprüft.
- Der Charakter wird per Skript erzeugt (`create_entity`) und per Teleport bewegt.
  Ob ein Skript-Charakter in allen Fällen minen und Inventar nutzen kann, zeigt erst der Praxistest.
- `connect` (Router), `snapshot`, `belt_neighbours`, `get_max_wire_distance`, Offshore-Pumpen-Platzierung und `game.server_save` sind nur gegen den Mock getestet.
- Der Boundary-Befehl für mehrteilige RCON-Antworten stammt aus phiresky/factorio-mcp
  (dort gegen echtes Factorio benutzt), hier aber nur gegen einen Fake-Server getestet.

## Ausbauideen

Züge (Gleise, Bahnhöfe, Fahrpläne), Öl und Chemie, Verteidigung, Ereignismeldungen vom Mod
(Angriff, Forschung fertig), Batch-Aufrufe, Import echter Blueprint-Strings, asynchrone Jobs mit `*_status` für längere Aktionen (Muster aus dem
Companion-Repo), ehrliches Laufen mit Pfadfindung.
