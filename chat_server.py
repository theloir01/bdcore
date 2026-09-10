"""
BDCore chat backend — "chat to my portfolio".

Sits between the dashboard (in your browser) and two other things it can't
safely talk to directly: your Neo4j database's credentials, and an Anthropic
API key. Flow per question:

  1. Query the real ConceptType / AttributeDefinition / RelationshipType
     nodes already in the graph (the schema load_schema.py created) to build
     a fresh, exact description of what's actually valid — not a hand-typed
     summary that goes stale the moment the schema changes. This is the same
     source of truth the dashboard's own canvas already reads live for its
     verb picker and attribute forms.
  2. Ask Claude to write a Cypher query that would answer the question,
     given that live schema description and recent conversation history, so
     follow-ups like "are you sure?" or "what about X instead?" have
     something to resolve against instead of being treated as a brand new,
     context-free question.
  3. Actually run that query against your real Neo4j database.
  4. If it errors, send the error back to Claude once and ask for a fix.
  5. Ask Claude to turn the real results into a concise, plain-English
     answer — grounded in what actually came back, not invented. Claude may
     add a second, clearly-labeled paragraph of general knowledge (e.g.
     explaining a term or typical industry practice) when it would genuinely
     help, but that paragraph is always kept structurally separate from the
     data-grounded answer, so it's obvious which part is a verified fact
     about this portfolio and which part is Claude's outside knowledge.

Run this alongside load_schema.py's Neo4j — same credentials — and your
own Anthropic API key from console.anthropic.com.
"""

import json
import os
import re
import sys
from flask import Flask, request, jsonify
from neo4j import GraphDatabase
import requests

# ---------------------------------------------------------------------------
# Set these as environment variables before running (or in a local .env
# file loaded by your shell) — never hard-code secrets in this file.
#   ANTHROPIC_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS = ["ANTHROPIC_API_KEY", "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
if missing:
    sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-sonnet-4-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

app = Flask(__name__)
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def build_schema_context():
    """
    Builds the schema description Claude sees fresh, from the real
    ConceptType / AttributeDefinition / RelationshipType nodes already
    sitting in the graph (created by load_schema.py) — the same source of
    truth the dashboard's own canvas queries live for its verb picker and
    attribute forms. This used to be a hand-typed string here that had to be
    manually kept in sync every time the schema changed, which is exactly
    the kind of thing that goes stale and causes an AI to guess. Querying
    the real nodes means new concepts/verbs are picked up automatically —
    and, more importantly, the relationship list below is the *exact*
    (source, verb, target) triples that are actually valid, not a flat list
    of verb names with no pairing — so there's no plausible-sounding verb
    left to invent.
    """
    with driver.session() as session:
        concept_rows = session.run(
            """
            MATCH (c:ConceptType)
            OPTIONAL MATCH (c)-[:HAS_ATTRIBUTE]->(a:AttributeDefinition)
            RETURN c.name AS concept,
                   collect(CASE WHEN a IS NULL THEN NULL ELSE {name: a.name, type: a.type, options: a.options} END) AS attrs
            ORDER BY c.name
            """
        ).data()
        rel_rows = session.run(
            """
            MATCH (r:RelationshipType)-[:HAS_SOURCE]->(s:ConceptType)
            MATCH (r)-[:HAS_TARGET]->(t:ConceptType)
            RETURN s.name AS source, r.verb AS verb, t.name AS target
            ORDER BY s.name, r.verb, t.name
            """
        ).data()

    concept_lines = []
    for row in concept_rows:
        attrs = [a for a in row["attrs"] if a]
        attr_bits = []
        for a in attrs:
            opts = a.get("options")
            if opts:
                opts_list = opts if isinstance(opts, list) else [opts]
                attr_bits.append(f'{a["name"]} (enum: {", ".join(str(o) for o in opts_list)})')
            else:
                attr_bits.append(f'{a["name"]} ({a.get("type", "string")})')
        concept_lines.append(f'- {row["concept"]}: name, status' + (", " + ", ".join(attr_bits) if attr_bits else ""))

    rel_lines = [f'{r["source"]} -- {r["verb"]} --> {r["target"]}' for r in rel_rows]
    valid_rel_types = {r["verb"].upper().replace(" ", "_") for r in rel_rows}

    schema_text = f"""
Every node has label :Instance PLUS its concept type, e.g. (:Instance:Application).

Concept types and their real attributes, queried live from the schema (not
hard-coded — if this list looks wrong, the schema in Neo4j is wrong, not this
description of it):
{chr(10).join(concept_lines)}

Every relationship also carries: criticality, status, strength (0-100), type.

The COMPLETE, EXACT set of valid (source type, verb, target type) triples —
this is everything that is actually allowed to connect to what. Cypher
relationship type = the verb, uppercased, spaces replaced with underscores
(e.g. "runs on" -> RUNS_ON). Do not use any relationship type not listed here:
{chr(10).join(rel_lines)}

Example queries:
MATCH (a:Instance:Application) WHERE a.owner IS NULL RETURN a.name
MATCH (r:Instance:Risk)-[:AFFECTS]->(n) RETURN r.name, n.name
MATCH (c:Instance:Capability)<-[:SUPPORTS]-(a:Instance:Application) RETURN c.name, count(a)
MATCH (j:Instance:Journey)-[:CONTAINS]->(js:Instance:JourneyStage) RETURN j.name, js.name ORDER BY js.sequence
MATCH (d:Instance:Decision)-[:SUPERSEDES]->(older:Instance:Decision) RETURN d.name, older.name
"""
    return schema_text, valid_rel_types


REL_TYPE_PATTERN = re.compile(r"\[:([A-Za-z_|]+)")


def find_invalid_relationship_types(cypher, valid_rel_types):
    """
    A hard, code-level check — not another prompt instruction hoping the
    model gets it right. Pulls every relationship type token actually used
    in the generated Cypher (handling OR-patterns like [:SUPPORTS|SUPPORTED_BY])
    and checks each against the real, live schema. This exists because
    prompt instructions alone have already demonstrably failed to stop this
    exact failure mode (SUPPORTED_BY invented alongside the real SUPPORTS,
    hedging rather than committing) even with the complete valid-triples list
    right there in the prompt. A non-existent relationship type doesn't
    error in Cypher, it silently matches nothing — this catches it before
    the query ever runs, deterministically, instead of hoping.
    """
    used = set()
    for match in REL_TYPE_PATTERN.finditer(cypher):
        for token in match.group(1).split("|"):
            if token:
                used.add(token)
    return sorted(used - valid_rel_types)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def call_claude(system, messages, max_tokens=1024):
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(block["text"] for block in data["content"] if block["type"] == "text")
    usage = data.get("usage", {})
    return text, {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}


def extract_cypher(text):
    # Strip markdown code fences if Claude adds them despite instructions
    match = re.search(r"```(?:cypher)?\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


def extract_json(text):
    # Same idea as extract_cypher, but for JSON responses — reusing
    # extract_cypher here would leave a stray "json" language tag as literal
    # garbage text in front of the real content, since that function only
    # knows to skip the word "cypher" specifically. This skips ANY
    # alphabetic language tag (json, or none at all).
    match = re.search(r"```[a-zA-Z]*\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


def run_cypher(statement):
    with driver.session() as session:
        result = session.run(statement)
        return [dict(record) for record in result]


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 204

    question = request.json.get("question", "").strip()
    history = request.json.get("history", [])  # [{role, content}, ...] — prior turns in this conversation
    if not question:
        return jsonify({"error": "No question provided"}), 400

    recent = history[-8:]
    history_text = "\n".join(f"{'You' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}" for h in recent)

    # Fresh from Neo4j on every request — this is a lightweight metadata
    # query (no LLM call), so there's no real cost to always being current
    # rather than caching and risking staleness.
    schema_context, valid_rel_types = build_schema_context()

    cypher_system = (
        "You write Cypher queries for a Neo4j database. Given the schema below and a "
        "question, respond with ONLY a valid Cypher query — no explanation, no markdown "
        "fences, nothing else. If the question can't be answered from this schema, "
        "respond with exactly: CANNOT_ANSWER\n\n" + schema_context + "\n\n"
        "Rules:\n"
        "- Never write an exact-match string filter on a name typed by the user (e.g. "
        "{name: \"...\"} or name = \"...\") — people mistype, use different capitalisation, "
        "or phrase things slightly differently than what's actually stored. Use "
        "toLower(x.name) CONTAINS toLower(\"...\") instead, unless the exact name came "
        "from a real result earlier in this same conversation.\n"
        "- Only filter on properties and enum values explicitly listed in the schema "
        "above. Don't invent a plausible-sounding property or value that isn't "
        "documented — if you're not sure a field exists on a given type, either query "
        "more broadly (e.g. return the node and let the answer stage look at what's "
        "actually there) or ask via CANNOT_ANSWER rather than guessing.\n"
        "- Only use relationship type names that exactly match a verb in the list above "
        "(uppercased, spaces replaced with underscores) — this is enforced in code, not "
        "just this instruction, so an invented relationship type will always bounce back "
        "as an error for you to correct. If you're not confident which direction a "
        "relationship goes for a given pair of types, write the pattern without a "
        "direction arrow (e.g. (a)-[:SUPPORTS]-(p)) so it matches either way.\n"
        "- When a question asks how many of something exist, support something, or relate "
        "to something, return BOTH the count AND each individual matched entity's id, "
        "name, and a literal type label matching its concept type (e.g. RETURN a.id AS id, "
        "a.name AS name, \"Application\" AS type) — not just a bare count — unless the "
        "match could plausibly be dozens or more, where listing every one wouldn't help.\n"
        "- If the current question is short and looks like it's substituting a new "
        "subject into the same kind of question as a recent turn (e.g. 'what about X', "
        "'and Y?', 'same for Z'), treat it as repeating that same query intent for the "
        "new subject — don't default to a generic 'describe this entity' query just "
        "because the new question on its own sounds open-ended.\n"
        "- If the question is a follow-up challenging or questioning a previous answer "
        "(e.g. 'are you sure', 'should it not be X', 'why not', 'I think there are N'), "
        "re-run a query that is AT LEAST AS BROAD as the one that produced that answer — "
        "same entities and relationship, just checked more thoroughly (fuzzy matching, "
        "both directions, related node types) — never switch to a different, narrower, "
        "or unrelated query that returns nothing and makes it look like the prior answer "
        "can no longer be explained. The goal is to actually re-verify the same claim, "
        "not to accidentally lose track of what was being checked."
    )
    cypher_user_content = f"Recent conversation:\n{history_text}\n\nCurrent question: {question}" if history_text else question

    total_usage = {"input": 0, "output": 0}

    def track(usage):
        total_usage["input"] += usage["input"]
        total_usage["output"] += usage["output"]

    def token_summary():
        return {**total_usage, "total": total_usage["input"] + total_usage["output"]}

    raw_cypher, usage = call_claude(cypher_system, [{"role": "user", "content": cypher_user_content}])
    track(usage)
    cypher = extract_cypher(raw_cypher)

    if cypher == "CANNOT_ANSWER":
        return jsonify({"answer": "I can't answer that from the current schema.", "cypher": None, "rowCount": 0,
                         "entities": [], "tokens": token_summary()})

    results = None
    error = None
    invalid_rels = find_invalid_relationship_types(cypher, valid_rel_types)
    if invalid_rels:
        error = f"This query uses relationship type(s) {invalid_rels} which don't exist in this schema. Valid relationship types are only: {sorted(valid_rel_types)}"
    else:
        try:
            results = run_cypher(cypher)
        except Exception as e:
            error = str(e)

    if error:
        # one retry, giving Claude the actual error (whether that's a Neo4j
        # exception or the code-level relationship-type check above)
        retry_prompt = f"That query failed with this error:\n{error}\n\nWrite a corrected Cypher query. Only the query, nothing else."
        raw_retry, usage = call_claude(
            cypher_system,
            [{"role": "user", "content": cypher_user_content}, {"role": "assistant", "content": cypher}, {"role": "user", "content": retry_prompt}],
        )
        track(usage)
        cypher = extract_cypher(raw_retry)
        retry_invalid = find_invalid_relationship_types(cypher, valid_rel_types)
        if retry_invalid:
            return jsonify({"answer": f"I couldn't write a valid query for that — it kept using a relationship type that doesn't exist ({retry_invalid}).",
                             "cypher": cypher, "rowCount": 0, "entities": [], "tokens": token_summary()})
        try:
            results = run_cypher(cypher)
        except Exception as e2:
            return jsonify({"answer": f"I couldn't run a valid query for that. Last error: {e2}", "cypher": cypher, "rowCount": 0,
                             "entities": [], "tokens": token_summary()})

    # Best-effort extraction of anything that looks like a real entity
    # (id + name present) so the frontend can render clickable references —
    # works regardless of exactly which fields a given query happened to
    # return, rather than requiring every query to conform to a strict shape.
    entities = []
    seen_ids = set()
    for row in (results or []):
        rid, rname = row.get("id"), row.get("name")
        if rid and rname and rid not in seen_ids:
            seen_ids.add(rid)
            entities.append({"id": rid, "name": rname, "type": row.get("type")})

    answer_system = (
        "You are chatting with someone about their application portfolio, in an ongoing "
        "conversation — not answering isolated one-off questions. Talk like you actually "
        "remember what's already been discussed, the way a colleague would, not like "
        "you're resetting to a formal template every time. Skip boilerplate openers like "
        "'Based on your data' — just answer.\n\n"
        "You were given a question and the real results of a database query against "
        "their own data. The data-grounded part of your answer must be based ONLY on "
        "the query results provided — never invent or assume facts about their specific "
        "portfolio that aren't in the results. If the results include named entities, "
        "list them by name (not just a count) so the person can see exactly which ones. "
        "If multiple rows came back, address all of them (or explicitly say you're only "
        "calling out the notable ones and why) — never silently drop rows the person can "
        "see were returned. If the results are empty, say so plainly rather than guessing, "
        "and if the question sounds like it expected a different answer, mention that the "
        "match might have been too strict rather than concluding there's simply nothing.\n\n"
        "If this question is challenging or pushing back on a previous answer ('are you "
        "sure', 'I think there are N', 'why not'): do not defer just because the person "
        "expressed confidence or a specific number. Re-check against the query results in "
        "front of you and decide based on the evidence, not social pressure. If the "
        "results still support the original answer, say so plainly and confidently, cite "
        "the specific evidence (e.g. exactly which entities were found), and don't ask the "
        "person to justify their own number as a way of avoiding a firm answer. Only "
        "change the answer if the results actually show something different this time.\n\n"
        "After that, if — and only if — general knowledge would genuinely help someone "
        "interpret or act on this answer (explaining what a term means, typical "
        "industry timelines, standard practice), add a separate paragraph starting "
        "with exactly 'General context (not from your data):'. Skip this entirely for "
        "simple factual lookups that don't need it. Never let general knowledge blur "
        "into, replace, or contradict the data-grounded answer above it — if the two "
        "would conflict, the query results are always right for this organisation."
    )
    answer_prompt = (
        (f"Recent conversation:\n{history_text}\n\n" if history_text else "") +
        f"Current question: {question}\n\nQuery results (JSON): {json.dumps(results, default=str)[:4000]}"
    )
    answer, usage = call_claude(answer_system, [{"role": "user", "content": answer_prompt}])
    track(usage)

    total_usage["total"] = total_usage["input"] + total_usage["output"]
    print(f"[{question[:60]!r}] tokens — input: {total_usage['input']}, output: {total_usage['output']}, total: {total_usage['total']}")

    return jsonify({"answer": answer, "cypher": cypher, "rowCount": len(results) if results else 0,
                     "entities": entities, "tokens": token_summary()})


# The canvas's shape palette — a purely visual, frontend-only concept with
# no representation in Neo4j at all, so unlike the schema this genuinely has
# to be hand-maintained here. If shapes are ever added to or removed from
# SHAPE_LIBRARY in the dashboard's source, this needs updating to match, or
# the AI will suggest shape keys that don't exist on the canvas.
SHAPE_LIBRARY_TEXT = """
Basic: rectangle, roundedrect, circle, lozenge, triangle, diamond
Cloud: cloud, server, database, storage, container, vm, function, cluster, cdn, queue
Network: loadbalancer, firewall, router, switch, vpn, apigateway, dns, vpc, internet, proxy
Security: lock, waf, iam, certificate, keymgmt, secgroup, audit, vpngateway
Generic: user, external, mobile, browser, api, dashboard, cache, backup
BPM: start, end, intermediate, task, gateway-x, gateway-and, gateway-or, dataobject, datastore, lane
"""


@app.route("/canvas-chat", methods=["POST", "OPTIONS"])
def canvas_chat():
    """
    Turns a plain-English drawing request into a structured plan the
    dashboard can execute on the Modelling Canvas — not a text answer like
    /chat. Two genuinely different things can happen per request, and the
    model decides which (or both) apply:

      - PULL: something plausibly already exists in the real portfolio —
        write a real, schema-validated Cypher query to find it (same
        guardrails as /chat: live schema, no invented relationship types).
      - CREATE: something doesn't exist yet — a new concept (lands as an
        unpushed draft, never auto-written to the graph), a shape (for
        illustrating steps/flow), or a sticky (for an informal note).

    The dashboard executes the returned plan using the same placement,
    import, and layout functions a person uses when building a canvas by
    hand — this endpoint only decides *what* to create, never touches
    Neo4j for anything in "create" (only for resolving "pull" queries).
    """
    if request.method == "OPTIONS":
        return "", 204

    request_text = request.json.get("request", "").strip()
    if not request_text:
        return jsonify({"error": "No request provided"}), 400

    schema_context, valid_rel_types = build_schema_context()

    plan_system = (
        "You help someone build a diagram on a visual canvas by describing what they "
        "want in plain English. Respond with ONLY a JSON object — no markdown fences, "
        "no explanation before or after — matching exactly this shape:\n\n"
        "{\n"
        '  "summary": "one short sentence describing what you\'re adding",\n'
        '  "pull": [ { "cypher": "a real Cypher query, schema-validated, that RETURNS '
        'id, name, and a literal type string per match, e.g. RETURN c.id AS id, c.name '
        'AS name, \\"Capability\\" AS type" } ],\n'
        '  "create": [\n'
        '    { "tempId": "n1", "kind": "concept", "conceptType": "<real concept type>", '
        '"name": "...", "attributes": { "<real attribute name>": "<value>" } },\n'
        '    { "tempId": "n2", "kind": "shape", "category": "<Basic|Cloud|Network|Security|'
        'Generic|BPM>", "shapeKey": "<real shape key>", "label": "..." },\n'
        '    { "tempId": "n3", "kind": "sticky", "text": "..." }\n'
        "  ],\n"
        '  "connections": [\n'
        '    { "from": "<tempId, or pull:QUERY_INDEX:ROW_INDEX for a pulled entity>", '
        '"to": "<same>", "kind": "concept", "verb": "<only for kind=concept — a real '
        'verb valid for that exact type pair>" },\n'
        '    { "from": "...", "to": "...", "kind": "shape", "label": "<only for '
        'kind=shape — any free text, or omit>" }\n'
        "  ]\n"
        "}\n\n"
        "Any section can be an empty array if not needed. Guidance on which kind to use:\n"
        "- \"pull\": when the request plausibly refers to something that already exists "
        "in their real portfolio — write a real query to find it, using fuzzy name "
        "matching (toLower(x.name) CONTAINS toLower(\"...\")), never an exact-match guess. "
        "Only use relationship types from the exact list below — this is validated in "
        "code and an invented one will bounce back as an error.\n"
        "- \"create\" kind=concept: for a genuine new BDCore entity that doesn't exist "
        "yet — only use real concept types and real attribute names from the schema "
        "below, and only enum values that are actually listed for that attribute. These "
        "land as drafts on the canvas, never automatically written to the graph.\n"
        "- \"create\" kind=shape, category BPM: for illustrating the STEPS of a process "
        "or flow — start event, one or more tasks, gateways where the flow branches, end "
        "event — not for representing a single named business entity.\n"
        "- \"create\" kind=sticky: for an informal note, open question, or idea that "
        "doesn't deserve to be a first-class concept or shape.\n"
        "- When the request asks for a MAP or HIERARCHY of things that already exist and "
        "are related to each other (e.g. \"draw a capability map\"), don't just pull a flat "
        "list — pull the relationship itself and connect the specific pulled rows to each "
        "other. This requires both queries to return rows in a GUARANTEED matching order, "
        "which needs an explicit, identical ORDER BY in both — Neo4j does not guarantee row "
        "order across separate queries otherwise, even for the same pattern. Worked example "
        "for \"draw a capability map\":\n"
        "  pull: [{\"cypher\": \"MATCH (parent:Instance:Capability)-[:CONTAINS]->(child:Instance:Capability) "
        "RETURN parent.id AS id, parent.name AS name, \\\"Capability\\\" AS type "
        "ORDER BY parent.id, child.id\"}, "
        "{\"cypher\": \"MATCH (parent:Instance:Capability)-[:CONTAINS]->(child:Instance:Capability) "
        "RETURN child.id AS id, child.name AS name, \\\"Capability\\\" AS type "
        "ORDER BY parent.id, child.id\"}]\n"
        "  Then connect pull:0:i to pull:1:i for each row index i — this only works because "
        "both queries sort by the exact same key over the exact same pattern, so row i in "
        "one is guaranteed to be the same relationship instance as row i in the other. If a "
        "capability has no children, it just won't appear in the second pull or in any "
        "connection — that's fine, it lands as an unconnected box, which is the honest "
        "answer when a capability genuinely has no children yet.\n"
        "- A single request can combine these. E.g. \"create a process to describe "
        "customer onboarding\" reasonably produces ONE Process concept (the formal "
        "entity, so it can later be pushed to the graph) AND a small BPM flow "
        "illustrating its steps (start -> task -> task -> end) as a separate visual "
        "group — concepts only connect to concepts with governed verbs, shapes only "
        "connect to shapes with free labels; there's no connector between the two "
        "groups on this canvas today, so don't invent a connection between them.\n"
        "- Keep it proportionate — a simple request should produce a simple plan. Don't "
        "pad out a 3-step process into 8 shapes just to seem thorough.\n\n"
        "Real, available shape keys by category:\n" + SHAPE_LIBRARY_TEXT + "\n\n"
        "Schema (concept types, attributes, and the exact valid relationship triples):\n"
        + schema_context
    )

    raw_plan, usage = call_claude(plan_system, [{"role": "user", "content": request_text}], max_tokens=2048)
    total_usage = {"input": usage["input"], "output": usage["output"]}

    try:
        plan_text = extract_json(raw_plan)
        plan = json.loads(plan_text)
    except Exception as e:
        return jsonify({"error": f"Couldn't parse a plan from that request: {e}", "raw": raw_plan,
                         "tokens": {**total_usage, "total": total_usage["input"] + total_usage["output"]}}), 200

    # Resolve every "pull" query against the real graph — same validation
    # guard as /chat, but no retry loop here (this endpoint returns the plan
    # either way; a bad pull query just yields an empty result for that step
    # rather than blocking everything else in the plan).
    pulled = []
    for pull_item in plan.get("pull", []):
        cypher = pull_item.get("cypher", "")
        invalid = find_invalid_relationship_types(cypher, valid_rel_types)
        if invalid:
            pulled.append({"cypher": cypher, "error": f"invalid relationship type(s): {invalid}", "rows": []})
            continue
        try:
            rows = run_cypher(cypher)
            pulled.append({"cypher": cypher, "rows": rows})
        except Exception as e:
            pulled.append({"cypher": cypher, "error": str(e), "rows": []})

    print(f"[canvas-chat: {request_text[:60]!r}] tokens — input: {total_usage['input']}, output: {total_usage['output']}")

    return jsonify({
        "summary": plan.get("summary", ""),
        "pulled": pulled,
        "create": plan.get("create", []),
        "connections": plan.get("connections", []),
        "tokens": {**total_usage, "total": total_usage["input"] + total_usage["output"]},
    })


@app.route("/refine-filters", methods=["POST", "OPTIONS"])
def refine_filters():
    """
    Maps a natural-language filter request onto real, existing filter chips
    on Portfolio Overview — status, criticality, disposition, hosting.
    Deliberately narrow: no Cypher, no Neo4j call at all, since filtering
    happens client-side on data already loaded. The model can't hallucinate
    a wrong chart or invent a relationship here — it's choosing from a fixed,
    real set of values, and anything it returns that isn't actually in that
    set gets stripped before it reaches the frontend, same validate-in-code
    discipline as the relationship-type guard used elsewhere in this file.
    """
    if request.method == "OPTIONS":
        return "", 204

    req_text = request.json.get("request", "").strip()
    options = request.json.get("options", {})
    if not req_text:
        return jsonify({"error": "No request provided"}), 400

    system = (
        "You map a natural-language filter request onto real, available filter options for an "
        "application portfolio table. Respond with ONLY a JSON object — no markdown fences, no "
        "explanation — with these keys: status, criticality, disposition, hosting (each an array "
        "of strings), search (a string), and summary (one short sentence describing what you set, "
        "written as if telling the person what you just did).\n\n"
        "Only use values that appear in the options lists below — never invent a value. An empty "
        "array for a dimension means 'no filter on this dimension' (show everything), not "
        "'exclude everything'. Only set search if the request names a specific application or "
        "vendor by name, not for general category filtering. If the request doesn't relate to any "
        "filterable dimension at all, return all empty arrays and say so plainly in summary.\n\n"
        f"Available options:\nstatus: {options.get('status', [])}\n"
        f"criticality: {options.get('criticality', [])}\n"
        f"disposition: {options.get('disposition', [])}\n"
        f"hosting: {options.get('hosting', [])}"
    )
    raw, usage = call_claude(system, [{"role": "user", "content": req_text}], max_tokens=400)
    total_usage = {"input": usage["input"], "output": usage["output"], "total": usage["input"] + usage["output"]}

    try:
        result = json.loads(extract_json(raw))
    except Exception as e:
        return jsonify({"error": f"Couldn't parse a filter selection from that: {e}", "tokens": total_usage}), 200

    def clean(key):
        real = set(options.get(key, []))
        vals = result.get(key)
        return [v for v in vals if v in real] if isinstance(vals, list) else []

    return jsonify({
        "status": clean("status"), "criticality": clean("criticality"),
        "disposition": clean("disposition"), "hosting": clean("hosting"),
        "search": result.get("search", "") if isinstance(result.get("search"), str) else "",
        "summary": result.get("summary", "") if isinstance(result.get("summary"), str) else "",
        "tokens": total_usage,
    })


if __name__ == "__main__":
    print("Chat backend running at http://localhost:5050")
    app.run(port=5050, debug=False)
