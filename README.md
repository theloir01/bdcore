# OntoCore

An enterprise architecture ontology platform — model your real portfolio
(applications, capabilities, risks, requirements, and how they all relate)
in Neo4j, explore and edit it through a single-page dashboard, and use an
AI assistant to query it in plain English or sketch options directly onto
a visual canvas.

## How it's built

- **`ontocore-dashboard.html`** — the entire dashboard. A single HTML
  file with React 18 and Babel Standalone loaded from the `vendor/`
  folder next to it (not a CDN), which transpiles the app's JSX in the
  browser at load time. There's no build step — you just serve this file.
- **`vendor/`** — the vendored React/Babel/Markdown/sanitizer scripts the
  HTML file loads. Must sit in the same folder as the HTML file.
- **`chat_server.py`** — a small local Flask backend that powers every AI
  feature (portfolio chat, filter refinement, and the canvas assistant).
  It holds your Anthropic API key and Neo4j credentials server-side so
  they never sit in the browser. It also serves `ontocore-dashboard.html`
  and `vendor/` itself, so this one process is the whole app — there's no
  separate static file server to run. The dashboard works fine without it
  for everything else (browsing, editing, the canvas) — only the AI
  features need it running.
- **`bdcore_schema.yaml`** / **`load_schema.py`** — the ontology's schema
  layer (concept types, attributes, valid relationship types) and the
  script that loads it into Neo4j.
- **`bdcore_rbl_instances.yaml`** / **`load_instances.py`** — a sample
  instance dataset (a fictional charity's application portfolio) and the
  script that loads it in. Swap in your own YAML to model a different
  organization.
- **`rbl-apm-dashboard-live.jsx`** — an early, no-longer-maintained
  reference copy of the frontend. The real, current source lives inside
  `ontocore-dashboard.html` itself (in the `<script type="text/plain"
  id="app-source">` block) — that's the file to edit.

## Prerequisites

- Python 3.9+
- A [Neo4j Aura](https://neo4j.com/product/auradb/) instance (the Free
  tier works) — create one and download its connection details
- An [Anthropic API key](https://console.anthropic.com/) — only needed
  for the AI features (chat, filter refinement, canvas assistant)

## Setup

1. **Create and activate a virtual environment, then install dependencies.**
   A venv keeps this project's packages (Flask, the Neo4j driver, etc.)
   separate from anything else on your system — the venv itself isn't
   committed (`venv/` is already gitignored).

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate

   pip install -r requirements.txt
   ```

   You'll need that same `source venv/bin/activate` in any new terminal
   before running `load_schema.py`, `load_instances.py`, or
   `chat_server.py` — it's what puts the packages you just installed on
   `PATH` for that shell.

2. **Configure credentials.** Copy `.env.example` to `.env` and fill in
   your real values (never commit `.env` — it's already gitignored):

   ```bash
   cp .env.example .env
   ```

   ```
   ANTHROPIC_API_KEY=
   NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=
   ```

3. **Load the ontology into Neo4j** (schema first, then sample data —
   both are idempotent, safe to re-run after editing the YAML):

   ```bash
   python load_schema.py
   python load_instances.py
   ```

4. **Start the server and open the dashboard.** This one process serves
   both the AI backend and the dashboard itself — no separate static
   file server needed:

   ```bash
   python chat_server.py
   ```

   Then open **http://localhost:5050/**.

   (You can still run the dashboard without `chat_server.py` — e.g.
   `python3 -m http.server 8000` and open
   `http://localhost:8000/ontocore-dashboard.html` — but the AI features
   won't work, since nothing is listening on `/chat`, `/canvas-chat`,
   etc.)

5. **Connect to your Aura instance.** On first load, the dashboard shows
   a "Connect to Your Aura Instance" screen — enter the same URI,
   username, and password from your `.env` file (and the database name,
   usually `neo4j`, from the `NEO4J_DATABASE` line in the credentials
   file Aura gave you). These are stored only in the browser's local
   storage, never sent anywhere but directly to Neo4j's Query API.

## Sharing a running instance

Since `chat_server.py` serves the whole app on one port, you can expose it
to someone else with a single [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/)
(no account needed for a quick link):

```bash
brew install cloudflared       # macOS; see Cloudflare's docs for other platforms
cloudflared tunnel --url http://localhost:5050
```

It prints a `https://*.trycloudflare.com` URL — share that. Anyone who has
it can reach the dashboard and the AI features while your `chat_server.py`
keeps running. These quick tunnels have no login wall, so don't leave one
up longer than you need it.

## Notes

- `chat_server.py` is a local process, not part of the deployed static
  HTML — if you pull a code update, restart it to actually pick up the
  change.
- Without `chat_server.py` running, the dashboard itself still works
  (browsing, editing, the canvas) — only the AI-powered features show a
  "couldn't reach the chat backend" message until it's started.
