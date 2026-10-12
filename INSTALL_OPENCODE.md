# Installation mit OpenCode (Linux)

Ziel: Ein lokales Modell (z. B. Qwen 27B) spielt über OpenCode Factorio 2.0. Du kannst parallel mitspielen.

```
OpenCode + lokales Modell <-stdio-> factorio-agent-mcp <-RCON-> Factorio-Server (Linux, headless) + Mod fac_agent
                                                                      ^ du joinst als Spieler
```

Stand: Alles ist gegen einen Mock getestet, noch nicht gegen ein echtes Factorio. Die Schritte zu OpenCode und
Factorio unten habe ich nach Dokumentation geschrieben, nicht auf deiner Maschine ausprobiert.

## 1. Voraussetzungen

- Linux, Python 3.10 oder neuer (`python3 --version`), `git`, `unzip`
- Factorio 2.0 (Kauf-Version zum Mitspielen) und die Headless-Version für den Server
  (Download: factorio.com, "Download", Headless, Linux). Beide müssen dieselbe Version haben.
- Ein lokales Modell mit Tool-Calling hinter einer OpenAI-kompatiblen Schnittstelle
  (llama.cpp `llama-server`, Ollama oder LM Studio)

## 2. OpenCode installieren

```bash
curl -fsSL https://opencode.ai/install | bash
# alternativ: npm i -g opencode-ai
opencode --version
```

## 3. Den MCP-Server installieren

```bash
cd ~
unzip factorio-agent-mcp.zip
cd factorio-agent-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

Der Befehl `~/factorio-agent-mcp/.venv/bin/factorio-agent-mcp` ist später der `command` in OpenCode.

## 4. Factorio-Server mit Mod und RCON

1. Headless-Version entpacken, z. B. nach `~/factorio`.
2. Mod installieren (Ordner `mods/` liegt im Factorio-Verzeichnis):
   ```bash
   cp ~/factorio-agent-mcp/dist/fac_agent_0.2.0.zip ~/factorio/mods/
   ```
   Beim Mitspielen legst du dieselbe Zip auch in den `mods/`-Ordner deines Spiel-Clients.
3. `~/factorio/server-settings.json` anlegen (Vorlage: `~/factorio/data/server-settings.example.json` aus dem Factorio-Ordner) und diese Werte setzen:
   ```json
   {
     "name": "Agent-Server",
     "visibility": { "public": false, "lan": true },
     "auto_pause": false,
     "allow_commands": "admins-only",
     "autosave_interval": 5
   }
   ```
   Wichtig ist `"auto_pause": false`. Sonst pausiert das Spiel, sobald kein Spieler verbunden ist, und der Agent
   merkt es nur an Meldungen wie "no game time passed".
4. Server starten:
   ```bash
   cp ~/factorio-agent-mcp/examples/start_factorio.sh ~/start_factorio.sh
   RCON_PASSWORD=geheim ~/start_factorio.sh
   ```
   Beim ersten Start wird die Karte `saves/agent.zip` erzeugt. In der Ausgabe sollte der Mod `fac_agent 0.2.0`
   geladen werden und RCON auf Port 27015 lauschen.
5. Optional als Dienst: eine `systemd`-Unit, die `start_factorio.sh` ausführt (`Restart=on-failure`).

Mitspielen: Im Spiel "Mehrspieler", "Mit Adresse verbinden", `ip-des-servers` (lokal `localhost`).

## 5. Lokales Modell bereitstellen

Beispiel llama.cpp (anderes: siehe Hinweise unten):

```bash
llama-server -m /pfad/zu/qwen-27b.gguf --port 8080 -c 65536 --jinja
```

`--jinja` schaltet das Tool-Calling-Template ein und ist für Qwen wichtig. Für Ollama gilt: Kontext
mindestens 16k bis 32k (`num_ctx`), sonst brechen Tool-Aufrufe leicht ab.

## 6. OpenCode konfigurieren

Lege im Projektordner, in dem du OpenCode startest (z. B. `~/factorio-play`), diese Dateien an:

```bash
mkdir -p ~/factorio-play && cd ~/factorio-play
cp ~/factorio-agent-mcp/examples/opencode.json .
cp ~/factorio-agent-mcp/examples/AGENTS.md .
```

In `opencode.json` ersetzt du `DU` durch deinen Benutzernamen, setzt das RCON-Passwort und passt den
Modellblock an (Port, Name, Kontextgröße). Die wichtigsten Teile:

```json
"mcp": {
  "factorio": {
    "type": "local",
    "command": ["/home/DU/factorio-agent-mcp/.venv/bin/factorio-agent-mcp"],
    "environment": {
      "FACTORIO_RCON_HOST": "127.0.0.1",
      "FACTORIO_RCON_PORT": "27015",
      "FACTORIO_RCON_PASSWORD": "geheim"
    },
    "enabled": true,
    "timeout": 15000
  }
}
```

- OpenCode setzt den Servernamen vor jedes Tool, das Modell sieht also `factorio_status`, `factorio_build` usw.
- `AGENTS.md` wird von OpenCode automatisch gelesen und enthält die Kurzanleitung für das Modell. Die ausführliche
  Anleitung liefert das Tool `factorio_guide`.
- Modelle für Ollama oder LM Studio: Block `provider` entsprechend anpassen (`baseURL` `http://localhost:11434/v1`
  bzw. `http://127.0.0.1:1234/v1`).

## 7. Selbsttest (zuerst ausführen)

Beim ersten Lauf in echtem Factorio führst du einmal den Selbsttest aus. Er prüft die API-Annahmen des Mods
(Platzieren, Drehen, Bänder, Strommasten, Craften, Abbau, Statistik, Chat, Speichern) in einem freien Sandbox-Bereich
und baut danach alles wieder ab. Inventar und Position werden zurückgesetzt.

Im OpenCode-Chat: "Rufe `factorio_selftest` auf und zeige mir den kompletten Bericht." Jede Zeile beginnt mit
`OK`, `WARN`, `FAIL` oder `SKIP`. Schick mir den Bericht, vor allem alle `FAIL`-Zeilen, dann passe ich den Mod an.
`SKIP` heißt nur, dass in der Nähe z. B. kein Wasser oder Erz war. Lauf den Test am besten nahe an Erz und Wasser
und mit einem Spielstand, in dem Gebäude wie Bohrer und Pumpe bereits freigeschaltet sind.

## 8. Testen

```bash
cd ~/factorio-play
opencode
```

Dann im Chat zum Beispiel:

1. "Rufe `factorio_status` auf." Erwartet: Position, Inventar und "next:"-Schritte.
   Kommt `ERR no_connection`, läuft der Server nicht oder Port/Passwort stimmen nicht.
   Kommt `mod_missing`, ist der Mod nicht geladen.
2. "Lies `factorio_guide` und fang an: sammle Kohle und Stein und baue einen Bohrer auf Eisen."
3. Im Spiel erscheinen Nachrichten als `[Bot] ...`. Du kannst im Spiel-Chat zurückschreiben, der Agent
   liest es mit `factorio_read_chat`.

Den Live-Viewer für dich öffnest du nach `factorio_render_map` unter `http://127.0.0.1:8765/`.

## 9. Tipps für lokale Modelle

- Wenn der Kontext knapp wird: weniger Tools aktivieren. In OpenCode kannst du einzelne Tools abschalten:
  ```json
  "tools": { "factorio_run_lua": false, "factorio_render_map": false }
  ```
  oder `FACTORIO_MCP_DISABLE_LUA=1` setzen, um `run_lua` ganz zu entfernen.
- Kleine Schritte funktionieren besser. Sag dem Modell Ziele wie "automatisiere Eisenplatten", nicht "gewinne das Spiel".
- Für Wiederholungen: `factorio_batch`. Für Fehlersuche: `factorio_machine_stats`, `factorio_trace_item`.
- Sichere vor Experimenten mit `factorio_checkpoint`.

## 10. Fehlersuche

| Problem | Ursache und Lösung |
|---|---|
| Tools erscheinen in OpenCode nicht | `command` falsch oder venv fehlt. Befehl im Terminal testen. `timeout` erhöhen (z. B. 15000). |
| `ERR no_connection` | Server läuft nicht, falsches Passwort oder Port. `ss -ltn | grep 27015`. |
| `ERR mod_missing` | Mod nicht im `mods/`-Ordner des Servers oder falsche Factorio-Version. |
| "no game time passed" | `auto_pause` ist an oder niemand verbunden. In `server-settings.json` auf `false`. |
| Modell ruft Tools falsch auf | Zu kleiner Kontext, fehlendes `--jinja`, oder Modell ohne gutes Tool-Calling. |
| Erfolge deaktiviert | Normal: Konsolenbefehle per RCON deaktivieren Achievements. |
| Fehler in einem Tool | Meldung enthält `try:` mit Hinweis. Ansonsten Serverlog (`factorio-current.log`) lesen. |

Beim ersten Lauf in echtem Factorio können kleine API-Abweichungen auftreten (siehe README, "Bekannte Unsicherheiten").
Melde mir die Fehlermeldung samt Log, dann passe ich den Mod an.
