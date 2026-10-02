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

import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import time
import uuid
from urllib.parse import urlencode, urlparse
from dotenv import load_dotenv
from flask import Flask, request, jsonify, redirect
from neo4j import GraphDatabase
import requests

load_dotenv()

# ---------------------------------------------------------------------------
# Set these as environment variables before running (or in a local .env
# file, loaded automatically above) — never hard-code secrets in this file.
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


def _cache_last(blocks):
    """
    Marks the last item of a content-block (or tool-definition) list as an
    Anthropic prompt-cache breakpoint, so everything up to and including it
    can be reused on the next call instead of being re-billed at full price.
    Returns a new list/dict — never mutates the caller's own data, since
    get_validated_plan's `convo` needs to stay exactly what it appended,
    not a copy with cache bookkeeping baked in.
    """
    if not blocks:
        return blocks
    blocks = list(blocks)
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks


def _messages_with_trailing_cache(messages):
    """
    Marks a cache breakpoint at the end of the LAST message only. Within
    get_validated_plan's tool-use loop, each call's message list is the
    previous call's list plus one newly-appended tool exchange — so caching
    the prior boundary means every round after the first only pays full
    price for what's actually new, instead of the entire accumulated
    conversation (tool results included) being rebilled every round.
    """
    if not messages:
        return messages
    messages = list(messages)
    last = dict(messages[-1])
    content = last["content"]
    content = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    last["content"] = content
    messages[-1] = last
    return messages


def call_claude_raw(system, messages, tools=None, max_tokens=1024, model=None):
    """
    The full Messages API call, returning the raw content blocks and stop
    reason rather than just concatenated text — call_claude below collapses
    this to the common case, but a tool-use loop (see get_validated_plan's
    tools/tool_executor) needs to see tool_use blocks and know whether
    Claude stopped to call one or actually finished.

    Marks cache breakpoints on the system prompt, the tool definitions, and
    the trailing edge of the conversation — the system prompt in particular
    (live schema + full canvas contents) is by far the largest, most
    repeated part of every call this file makes, and was previously sent
    and billed in full on every single round of a multi-step tool-use loop.

    `model` lets a caller route a given task to whichever model id the
    Admin has configured for that cost tier (see resolve_models) — falls
    back to CLAUDE_MODEL so any caller that doesn't care still works
    exactly as before.
    """
    resolved_model = model or CLAUDE_MODEL
    payload = {
        "model": resolved_model, "max_tokens": max_tokens,
        "system": _cache_last([{"type": "text", "text": system}]),
        "messages": _messages_with_trailing_cache(messages),
    }
    if tools:
        payload["tools"] = _cache_last(tools)
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return data.get("content", []), data.get("stop_reason"), {
        # The actual model id this call was billed against — carried on the
        # usage dict itself (rather than the caller having to separately
        # remember what it passed in) so add_usage can bucket cost by model.
        # A single logical request can span two different-priced models
        # (e.g. Cypher generation on the low-cost tier, the answer on the
        # high-cost one) — a merged total would make an accurate $ cost
        # impossible to compute downstream.
        "model": resolved_model,
        "input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
        "cacheRead": usage.get("cache_read_input_tokens", 0), "cacheWrite": usage.get("cache_creation_input_tokens", 0),
    }


def call_claude(system, messages, max_tokens=1024, model=None):
    content_blocks, _, usage = call_claude_raw(system, messages, max_tokens=max_tokens, model=model)
    text = "".join(block["text"] for block in content_blocks if block["type"] == "text")
    return text, usage


DEFAULT_LOW_COST_MODEL = "claude-haiku-4-5-20251001"


def resolve_models(data):
    """
    Reads the Admin-configured low/high-cost model ids out of a request
    body's "models" field (see the Admin -> AI Models page), falling back
    to sane defaults — CLAUDE_MODEL (Sonnet) for high-cost, Haiku for
    low-cost — for any request that predates this field or left a tier
    blank. Keeps the actual choice of WHICH id means "cheap" vs
    "expensive" entirely client-configurable, while which TASK uses which
    tier stays a code decision below.
    """
    models = data.get("models") or {}
    high = (models.get("highCost") or "").strip() or CLAUDE_MODEL
    low = (models.get("lowCost") or "").strip() or DEFAULT_LOW_COST_MODEL
    return low, high


USAGE_KEYS = ("input", "output", "cacheRead", "cacheWrite")


def empty_usage():
    return {"byModel": {}}


def add_usage(total, usage):
    """
    Accumulates one call's usage dict (from call_claude_raw — has "model"
    plus the four USAGE_KEYS) into a running total, bucketed by model id.
    A single endpoint can route different steps to different cost tiers
    (see resolve_models), so the per-model breakdown is what makes an
    accurate $ cost computable downstream — a flat merged total can't tell
    you how many tokens were billed at which rate.
    """
    model = usage.get("model") or "unknown"
    bucket = total["byModel"].setdefault(model, {k: 0 for k in USAGE_KEYS})
    for k in USAGE_KEYS:
        bucket[k] += usage.get(k, 0)


def usage_with_total(usage):
    total_tokens = sum(sum(bucket.values()) for bucket in usage["byModel"].values())
    return {**usage, "total": total_tokens}


def usage_log_str(usage):
    if not usage["byModel"]:
        return "no usage"
    return " | ".join(
        f"{model}: input={u['input']}, output={u['output']}, cacheRead={u['cacheRead']}, cacheWrite={u['cacheWrite']}"
        for model, u in usage["byModel"].items()
    )


def extract_cypher(text):
    # Strip markdown code fences if Claude adds them despite instructions
    match = re.search(r"```(?:cypher)?\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


SUPPORTED_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def parse_data_url(data_url):
    """
    Splits a "data:image/png;base64,AAAA..." string (exactly what the
    dashboard's canvas image upload already produces and stores) into
    (media_type, base64_data) for Anthropic's image content block. Returns
    (None, None) if it isn't a data URL the vision API can actually accept —
    notably SVG, which the canvas image tool allows but Claude's vision
    input does not (it only takes raster formats), so that has to be caught
    here rather than failing opaquely inside the API call.
    """
    match = re.match(r"^data:([\w./+-]+);base64,(.+)$", data_url, re.DOTALL)
    if not match:
        return None, None
    media_type = match.group(1)
    if media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        return None, None
    return media_type, match.group(2)


def extract_json(text):
    # Same idea as extract_cypher, but for JSON responses — reusing
    # extract_cypher here would leave a stray "json" language tag as literal
    # garbage text in front of the real content, since that function only
    # knows to skip the word "cypher" specifically. This skips ANY
    # alphabetic language tag (json, or none at all).
    match = re.search(r"```[a-zA-Z]*\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


def describe_pull_outcome(pull_requested, pulled):
    """
    A truthful, deterministic sentence about what "pull" actually found,
    built entirely from the real query results — never from the model.
    The model writes "reply" in the same turn it decides what to pull, i.e.
    before any of those queries have actually run against the database, so
    it has no way to know yet whether a given name matched anything real.
    Left unchecked, that produces exactly the failure mode this exists to
    prevent: a confident "I've pulled in the four applications" when the
    query actually matched zero rows. This is prepended to the model's own
    reply (which is now instructed to only describe what it created).
    Returns None when nothing was requested to pull (nothing to report).
    """
    if not pull_requested:
        return None
    found, any_missing = [], False
    for p in pulled:
        rows = p.get("rows") or []
        if rows:
            found.extend(r.get("name") for r in rows if r.get("name"))
        else:
            any_missing = True
    if found and any_missing:
        return f"Found and pulled in: {', '.join(found)}. I couldn't find a match for the rest — double-check those names and try again."
    if found:
        return f"Pulled in: {', '.join(found)}."
    return "I couldn't find a match in the portfolio for what you asked me to pull in — double-check the exact names and try again."


def get_validated_plan(system, messages, max_tokens=2048, tools=None, tool_executor=None, max_tool_rounds=4, model=None):
    """
    Calls Claude and parses its JSON plan, retrying once if the response
    comes back empty or unparseable. The Anthropic API occasionally returns
    a completion with no text content for no discoverable reason on our end
    — rare, but this endpoint's prompt (full schema + shape library + a
    growing conversation history) is by far the longest in this file, so
    it's the one place that's actually shown it. A single silent retry
    clears it almost every time; only surface an error to the person if it
    fails twice in a row.

    With tools + tool_executor given (canvas-chat's connected MCP servers),
    Claude can stop mid-turn to call one or more of them — e.g. searching a
    Miro board by name, then fetching its contents — before producing the
    final plan. Each tool_use block is handed to tool_executor(name, input),
    which must return (result_text, is_error); the loop feeds tool_result
    turns back and continues until Claude stops asking for tools or
    max_tool_rounds is hit, at which point it's nudged to answer with
    whatever it has rather than looping forever. The conversation (including
    any tool exchanges) carries over into the one JSON-parse retry below,
    so a retry doesn't have to re-fetch the same tool results again.

    Returns (plan_dict_or_None, raw_text_of_last_attempt, total_usage_dict).
    """
    total_usage = empty_usage()
    plan, raw_plan = None, ""
    convo = list(messages)
    for attempt in range(2):
        rounds = 0
        while True:
            # Once the round cap is hit, stop offering tools entirely —
            # with nothing left to call, Claude is structurally forced to
            # answer in text instead of requesting yet another round (the
            # API can't return stop_reason "tool_use" when no tools were
            # offered). Without this, a request needing more tool calls
            # than the cap allows (e.g. listing boards, then fetching one,
            # then something else) can keep asking for tools until this
            # function gives up on an empty response that never had a
            # chance to contain the plan.
            offer_tools = tools if rounds < max_tool_rounds else None
            convo_this_call = convo
            if offer_tools is None and tools:
                convo_this_call = convo + [{"role": "user", "content":
                    "Stop calling tools now and answer with ONLY the final JSON plan, in the exact shape "
                    "described above, based on whatever you've already found."}]
            content_blocks, stop_reason, usage = call_claude_raw(system, convo_this_call, tools=offer_tools, max_tokens=max_tokens, model=model)
            add_usage(total_usage, usage)
            if stop_reason == "tool_use" and tool_executor and offer_tools:
                convo.append({"role": "assistant", "content": content_blocks})
                tool_results = []
                for block in content_blocks:
                    if block.get("type") != "tool_use":
                        continue
                    result_text, is_error = tool_executor(block["name"], block.get("input") or {})
                    tool_result = {"type": "tool_result", "tool_use_id": block["id"], "content": result_text}
                    if is_error:
                        tool_result["is_error"] = True
                    tool_results.append(tool_result)
                convo.append({"role": "user", "content": tool_results})
                rounds += 1
                continue
            raw_plan = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            break
        try:
            plan = json.loads(extract_json(raw_plan))
            break
        except Exception as e:
            print(f"[canvas-chat] attempt {attempt + 1} failed to parse a plan ({e}); raw length={len(raw_plan)}")
            plan = None
    return plan, raw_plan, total_usage


_WRITE_CYPHER_RE = re.compile(r"(?i)\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH)\b")


def run_cypher(statement):
    """
    Every Cypher statement actually reaching Neo4j from this file — whether
    model-written (a "pull" entry, or now the live query_portfolio tool) or
    not — passes through here, so this is the one place to enforce
    read-only. Nothing upstream validates for this today beyond prompt
    instructions asking for RETURN-only queries; giving the model a live,
    mid-turn tool to call this more freely (see make_pull_tool_executor)
    is exactly the reason to stop relying on instructions alone.
    """
    if _WRITE_CYPHER_RE.search(statement):
        raise ValueError("Only read-only queries are allowed here — no CREATE/MERGE/DELETE/SET/REMOVE/DROP.")
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
    low_model, high_model = resolve_models(request.json)

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

    total_usage = empty_usage()

    def track(usage):
        add_usage(total_usage, usage)

    def token_summary():
        return usage_with_total(total_usage)

    raw_cypher, usage = call_claude(cypher_system, [{"role": "user", "content": cypher_user_content}], model=low_model)
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
            model=low_model,
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
    answer, usage = call_claude(answer_system, [{"role": "user", "content": answer_prompt}], model=high_model)
    track(usage)

    print(f"[{question[:60]!r}] tokens — {usage_log_str(total_usage)}, total: {usage_with_total(total_usage)['total']}")

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


def custom_palette_guidance(custom_palettes):
    """
    Describes whatever vendor icon packs (AWS, Azure, Cisco, …) this
    customer has actually imported via "+ Import Palette" — key/label pairs
    only, never the real images, since the model needs to know which real
    icons exist and what to call them, not render them. Returns "" when
    none are installed, so the prompt doesn't dangle an empty section.

    This exists because without it, "create" shapes have only ever been able
    to come from the built-in generic Cloud/Network/Security/Generic/Basic
    set below — there was no way for the model to know a real, branded icon
    pack was sitting right there, so even a request naming a specific vendor
    (or reading a screenshot of an actual vendor diagram) could only ever
    produce a generic composition, never the real icons a customer went to
    the trouble of importing.
    """
    if not custom_palettes:
        return ""
    lines = []
    for pack in custom_palettes:
        icons = pack.get("icons") or []
        if not icons:
            continue
        icon_list = ", ".join(f'"{ic.get("key")}" ({ic.get("label")})' for ic in icons if ic.get("key"))
        lines.append(f'- Pack "{pack.get("name")}" — use category: "{pack.get("id")}" for any shape from it. Icons: {icon_list}')
    if not lines:
        return ""
    return (
        "\n\nInstalled custom icon packs — real, branded icons this customer has imported, distinct from "
        "the generic shape library above:\n" + "\n".join(lines) + "\n"
        "When something you're creating plausibly matches one of these real icons — especially when the "
        "source image or text is itself about that exact vendor (an AWS diagram, an Azure architecture, "
        "etc) — strongly prefer the real installed icon over the closest generic Cloud/Network/Security "
        "equivalent. Use the icon's own \"key\" as shapeKey and its pack's category value exactly as given "
        "above (not one of Basic/Cloud/Network/Security/Generic/BPM). Only fall back to a generic shape "
        "when nothing installed actually fits what you're depicting."
    )


def plan_create_guidance(schema_context, canvas_snapshot, custom_palettes=None):
    """
    Shared by /canvas-chat and /canvas-interpret: which "create" kind to use,
    the pull-vs-create split, worked examples, the real shape library, the
    live schema, and current canvas contents. Factored out once so both
    endpoints work from the exact same rules about what a valid plan looks
    like, rather than two hand-maintained copies that can quietly drift
    apart — the same reasoning build_schema_context() itself exists for.
    """
    return (
        "Guidance on which kind to use for the drawing sections themselves:\n"
        "- \"pull\": when the request plausibly refers to something that already exists "
        "in their real portfolio — write a real query to find it, using fuzzy name "
        "matching (toLower(x.name) CONTAINS toLower(\"...\")), never an exact-match guess. "
        "Only use relationship types from the exact list below — this is validated in "
        "code and an invented one will bounce back as an error. When the request names "
        "SEVERAL specific, distinct things by name (e.g. \"pull in App A, App B, and App "
        "C\"), write ONE pull query PER named thing rather than combining them into a "
        "single query with OR conditions — each query's real result is reported back to "
        "the person individually (see the reply guidance above), so one combined query "
        "makes it impossible to tell them which specific ones were and weren't actually "
        "found.\n"
        "- \"create\" kind=concept: for a genuine new BDCore entity that doesn't exist "
        "yet — only use real concept types and real attribute names from the schema "
        "below, and only enum values that are actually listed for that attribute. These "
        "land as drafts on the canvas, never automatically written to the graph.\n"
        "- \"create\" kind=shape, category BPM: for illustrating the STEPS of a process "
        "or flow — start event, one or more tasks, gateways where the flow branches, end "
        "event — not for representing a single named business entity.\n"
        "- \"create\" kind=sticky: for an informal note, open question, or idea that "
        "doesn't deserve to be a first-class concept or shape.\n"
        "- \"x\" and \"y\" on any create item are optional and almost always left out — only "
        "set them when you're recreating something whose source had a real, known layout "
        "(a whiteboard photo, a pasted board, a fetched external board's own items) and you "
        "want that relative arrangement preserved (don't invent or estimate a position for "
        "something with no known layout). Set them to the item's true CENTER point, computed "
        "from whatever position/size data the source actually gives you — never copy a raw "
        "position field verbatim without checking what it means, since a source's position "
        "field is frequently a TOP-LEFT corner (not a center) paired with a separate "
        "width/height, and copying that corner as-is systematically drags bigger items away "
        "from where they actually visually sit relative to smaller ones next to them. A tool "
        "result that contains Miro canvas-composer elements comes with an "
        "\"[Extracted absolute center positions...]\" block appended to it — a ready-made "
        "miroId -> centerX/centerY lookup, already computed server-side for exactly this "
        "purpose. When that block is present, READ THE CENTERX/CENTERY VALUES DIRECTLY FROM IT "
        "and copy them as a \"create\" item's x/y for the matching miroId — do not parse the "
        "raw SVG's own x/y/cx/cy yourself (Miro's native "
        "convention varies by element type: top-left for a rect/sticky/shape, center for a "
        "circle/ellipse, baseline-anchor for text, relative to its parent frame's own translate "
        "when nested — the extracted block has already resolved all of that). Without that "
        "block, work out whatever convention the source's own data is actually using and "
        "compute each item's true center yourself. Leaving x/y out entirely (the normal case, "
        "no known layout to preserve) lets placement pick a sensible spot automatically.\n"
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
        "pad out a 3-step process into 8 shapes just to seem thorough.\n"
        "- \"recolor\": for requests about how existing canvas objects should look — "
        "\"colour these by risk\", \"highlight anything overdue for review\", \"make the "
        "unowned ones stand out\" — not for adding anything new. Judge each object in "
        "CURRENT CANVAS CONTENTS below against the request using whatever data it carries "
        "(a concept pulled from the real portfolio carries a \"realData\" block — risks, "
        "criticality, disposition, status, hosting, AI readiness/relevance, business value, "
        "technical health; a plain draft concept only has its own attributes; a shape or "
        "sticky only has its label/text) — only recolor objects the request's criteria "
        "actually applies to, leave the rest out of the array entirely rather than resetting "
        "them. Prefer a small, consistent palette that reads as intentional rather than "
        "decorative — red/orange for something genuinely concerning, amber for worth "
        "watching, green for healthy/low-risk, blue or grey for neutral/informational — "
        "unless the request's own criteria calls for something else (e.g. \"colour by "
        "concept type\" wants one consistent color per type, not a risk gradient). A short "
        "\"label\" badge (2-3 words) is a nice addition when it adds real information (e.g. "
        "\"No DR Coverage\") but skip it when the color alone already says enough. A request "
        "combining recolor with pull/create is fine — e.g. \"pull in the Payments capability "
        "and colour everything by criticality\" pulls first, then recolors the full "
        "resulting set including anything just pulled in (reference newly-created objects "
        "in \"recolor\" by their tempId, exactly like a connection would).\n"
        "- Reference architectures and frameworks (\"add an AWS reference architecture for "
        "a 3-tier web app\", \"lay out the NIST CSF functions\"): there's no AWS/NIST-branded "
        "shape set — compose one from the generic Cloud/Network/Security/Generic/Basic shapes "
        "below, labelled with the real vendor/framework terms, the same way a real architect "
        "would sketch it on a whiteboard. Worked example, \"a basic AWS 3-tier web app\":\n"
        "  create: [\n"
        "    {\"tempId\": \"a1\", \"kind\": \"shape\", \"category\": \"Network\", \"shapeKey\": \"internet\", \"label\": \"Internet\"},\n"
        "    {\"tempId\": \"a2\", \"kind\": \"shape\", \"category\": \"Security\", \"shapeKey\": \"waf\", \"label\": \"AWS WAF\"},\n"
        "    {\"tempId\": \"a3\", \"kind\": \"shape\", \"category\": \"Network\", \"shapeKey\": \"loadbalancer\", \"label\": \"Application Load Balancer\"},\n"
        "    {\"tempId\": \"a4\", \"kind\": \"shape\", \"category\": \"Network\", \"shapeKey\": \"vpc\", \"label\": \"VPC\"},\n"
        "    {\"tempId\": \"a5\", \"kind\": \"shape\", \"category\": \"Cloud\", \"shapeKey\": \"vm\", \"label\": \"Web Tier (EC2 Auto Scaling)\"},\n"
        "    {\"tempId\": \"a6\", \"kind\": \"shape\", \"category\": \"Cloud\", \"shapeKey\": \"vm\", \"label\": \"App Tier (EC2 Auto Scaling)\"},\n"
        "    {\"tempId\": \"a7\", \"kind\": \"shape\", \"category\": \"Cloud\", \"shapeKey\": \"database\", \"label\": \"RDS (Multi-AZ)\"},\n"
        "    {\"tempId\": \"a8\", \"kind\": \"shape\", \"category\": \"Cloud\", \"shapeKey\": \"storage\", \"label\": \"S3\"},\n"
        "    {\"tempId\": \"a9\", \"kind\": \"shape\", \"category\": \"Security\", \"shapeKey\": \"iam\", \"label\": \"IAM Roles\"}\n"
        "  ],\n"
        "  connections: [ {\"from\": \"a1\", \"to\": \"a2\", \"kind\": \"shape\"}, {\"from\": \"a2\", \"to\": \"a3\", \"kind\": \"shape\"}, "
        "{\"from\": \"a3\", \"to\": \"a4\", \"kind\": \"shape\"}, {\"from\": \"a4\", \"to\": \"a5\", \"kind\": \"shape\"}, "
        "{\"from\": \"a5\", \"to\": \"a6\", \"kind\": \"shape\"}, {\"from\": \"a6\", \"to\": \"a7\", \"kind\": \"shape\"}, "
        "{\"from\": \"a6\", \"to\": \"a8\", \"kind\": \"shape\"} ]\n"
        "  (IAM left unconnected — it governs the whole thing, not a step in the request flow; "
        "that's fine, not every box needs a line.) A framework taxonomy like NIST CSF is "
        "simpler — one Basic \"roundedrect\" shape per function (Identify, Protect, Detect, "
        "Respond, Recover), each labelled with the real function name, usually with no "
        "connections at all since it's a taxonomy, not a flow. Same proportionality rule "
        "applies: a request for \"the AWS reference architecture\" with no more detail should "
        "get a recognisable, simple sketch like the one above, not an exhaustive rebuild of "
        "every AWS service that could theoretically be involved.\n\n"
        "Real, available shape keys by category:\n" + SHAPE_LIBRARY_TEXT
        + custom_palette_guidance(custom_palettes) + "\n\n"
        "Schema (concept types, attributes, and the exact valid relationship triples):\n"
        + schema_context + "\n\n"
        "CURRENT CANVAS CONTENTS — the full text/attributes of everything already there "
        "(including real portfolio data for anything pulled in). This is what \"recolor\" "
        "judges objects against, what tells you whether something the request describes "
        "already exists so you don't duplicate it, and what most questions in \"reply\" "
        "should be answered from:\n"
        + (json.dumps(canvas_snapshot) if canvas_snapshot else "The canvas is currently empty.")
    )


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
    _, high_model = resolve_models(request.json)
    canvas_snapshot = request.json.get("canvas", [])
    custom_palettes = request.json.get("customPalettes", [])
    # Prior turns in this canvas's chat thread — {role: "user"|"assistant", content}
    # — so a follow-up like "out of those options which would you recommend?"
    # resolves "those options" against what was actually just said, on top of
    # CURRENT CANVAS CONTENTS below already carrying their full text. Capped
    # to keep the prompt bounded on a long-running session.
    history = [h for h in request.json.get("history", []) if h.get("role") in ("user", "assistant") and h.get("content")][-16:]
    # The connected MCP servers the frontend already knows about (Admin ->
    # Integrations), with whatever tools it last discovered for each — lets
    # a request like "bring in My First Frame from Miro" actually reach out
    # and fetch it, by giving Claude real tool-calling access rather than
    # us trying to detect that intent by matching text. See
    # get_validated_plan's tools/tool_executor for the actual loop.
    mcp_servers = request.json.get("mcpServers", [])
    mcp_tools, mcp_tool_lookup = mcp_tools_to_anthropic(mcp_servers)
    refreshed_auths = {}
    mcp_tool_executor = make_mcp_tool_executor(mcp_tool_lookup, refreshed_auths) if mcp_tools else None
    # Skills this chat has explicitly opted into (Admin -> Skills Creator
    # defines them; buildActiveSkillsSummary on the frontend only sends the
    # ones actually added here) — each is just a name + reusable prompt
    # folded into this turn's own instructions below, same trust level as
    # everything else already in plan_system: it can steer what gets
    # pulled/created/connected, never anything outside that.
    active_skills = [s for s in request.json.get("skills", []) if isinstance(s, dict) and (s.get("prompt") or "").strip()]

    schema_context, valid_rel_types = build_schema_context()

    # query_portfolio (PULL_TOOL) is offered on every request, not just
    # when an MCP server is connected — it's what lets a "pull the real
    # data, then reason about it" skill (6R rationalization, capability
    # gap analysis) actually see results mid-turn instead of writing its
    # reply blind, before a plain "pull" entry even runs. See PULL_TOOL's
    # own description for how it relates to "pull".
    pull_tool_executor = make_pull_tool_executor(valid_rel_types)
    tools = [PULL_TOOL] + mcp_tools

    def tool_executor(name, arguments):
        if name == PULL_TOOL_NAME:
            return pull_tool_executor(name, arguments)
        if mcp_tool_executor:
            return mcp_tool_executor(name, arguments)
        return f"Unknown tool {name!r}.", True

    plan_system = (
        "You help someone build a diagram on a visual canvas by describing what they "
        "want in plain English, and answer questions about what's on it — this is a "
        "running conversation, not a one-shot command line. Respond with ONLY a JSON "
        "object — no markdown fences, no explanation before or after — matching "
        "exactly this shape:\n\n"
        "{\n"
        '  "reply": "what you say back in the chat thread — see below for the two '
        'cases this covers",\n'
        '  "pull": [ { "cypher": "a real Cypher query, schema-validated, that RETURNS '
        'id, name, and a literal type string per match, e.g. RETURN c.id AS id, c.name '
        'AS name, \\"Capability\\" AS type" } ],\n'
        '  "create": [\n'
        '    { "tempId": "n1", "kind": "concept", "conceptType": "<real concept type>", '
        '"name": "...", "attributes": { "<real attribute name>": "<value>" }, "x": <optional number>, "y": <optional number> },\n'
        '    { "tempId": "n2", "kind": "shape", "category": "<Basic|Cloud|Network|Security|'
        'Generic|BPM, OR an installed custom pack\'s own id — see below>", "shapeKey": '
        '"<real shape key — a built-in one below, or an installed custom pack\'s own icon key>", "label": "...", '
        '"x": <optional number>, "y": <optional number>, "width": <optional number>, "height": <optional number> },\n'
        '    { "tempId": "n3", "kind": "sticky", "text": "...", "x": <optional number>, "y": <optional number> }\n'
        "  ],\n"
        '  "connections": [\n'
        '    { "from": "<tempId, or pull:QUERY_INDEX:ROW_INDEX for a pulled entity>", '
        '"to": "<same>", "kind": "concept", "verb": "<only for kind=concept — a real '
        'verb valid for that exact type pair>" },\n'
        '    { "from": "...", "to": "...", "kind": "shape", "label": "<only for '
        'kind=shape — any free text, or omit>" }\n'
        "  ],\n"
        '  "recolor": [\n'
        '    { "id": "<a real id from CURRENT CANVAS CONTENTS below — never a tempId, '
        'this only ever applies to objects already on the canvas>", '
        '"color": "<a hex color, or null to clear a highlight back to default>", '
        '"label": "<a short badge word/phrase, e.g. \'High Risk\' — optional, omit for none>" }\n'
        "  ]\n"
        "}\n\n"
        "Any section can be an empty array if not needed. \"reply\" covers two different "
        "situations — decide which one this request is before writing it:\n"
        "- The request asks for something to be drawn/changed (the pull/create/"
        "connections/recolor sections below do the actual work): write 1-3 sentences "
        "describing what you CREATED — new concepts, shapes, or stickies, and how "
        "things connect. When you sketched multiple options or alternatives (e.g. "
        "several stickies laying out different approaches), name each one and its key "
        "feature/tradeoff in a sentence, so the reply alone tells the whole story "
        "without having to read every sticky — e.g. \"I sketched three DR options: a "
        "cloud-native rebuild (fastest RTO, highest cost), a warm standby on a "
        "secondary site (moderate cost and speed), and a backup-and-restore runbook "
        "(cheapest, slowest to recover).\" Do not describe HOW you found things (which "
        "queries ran, etc) — that's shown separately in the UI. Critically: do NOT "
        "claim anything about whether a \"pull\" query actually found or added "
        "something — you're writing this before that query has even run against the "
        "real database, so you cannot know yet whether it matched anything. A "
        "separate, truthful line reporting exactly what was and wasn't found gets "
        "added automatically in front of your reply — write only about the part you "
        "actually control (what you created).\n"
        "- The request is a question — about what's already on the canvas, or a "
        "follow-up on the conversation so far (\"which of those would you recommend?\", "
        "\"what's the risk with option 2?\", \"how does this compare to our other CRM "
        "apps?\") — answer it directly and substantively in \"reply\", grounded in "
        "CURRENT CANVAS CONTENTS below (which carries the full text/attributes of "
        "everything already there, including real portfolio data for anything "
        "pulled in) and the conversation history you've been given. Give a real "
        "answer with real reasoning — \"which would you recommend\" deserves an actual "
        "pick and why, not a recap of the options back at them. Leave pull/create/"
        "connections/recolor all empty for a pure question — don't invent something "
        "to draw just because those sections exist.\n"
        "- A request can combine both — e.g. \"add a fourth option and tell me which of "
        "all four you'd pick\" both creates something and answers in the same reply.\n\n"
        + plan_create_guidance(schema_context, canvas_snapshot, custom_palettes)
        + ("\n\nYou also have a live, read-only tool called \"query_portfolio\" that runs a real Cypher query "
           "against the portfolio graph and returns the actual rows — use it whenever a request needs you to "
           "reason about real data (comparing applications, an application's actual attributes, what supports "
           "a capability, tracing a dependency or risk) before you can honestly answer or decide what to draw, "
           "instead of writing a \"pull\" entry and reasoning about data you haven't actually seen. Call it, "
           "read what comes back, and only THEN write your \"reply\" and the rest of your plan — the warning "
           "above about not claiming things from a \"pull\" that hasn't run yet does not apply to data you've "
           "actually seen this way: once you've called query_portfolio and read its real results, you "
           "genuinely know what they contain and can reason about them for real, right in this same reply. "
           "This tool only lets you see data for your own reasoning — it never places anything on the canvas "
           "by itself. If the entities you found this way should also actually appear on the canvas (not just "
           "inform what you say or draw), still add them to \"pull\" in your final plan the normal way — the "
           "two serve different purposes and often both apply to the same request.")
        + ("\n\nYou also have live tools connected to these outside sources: "
           + ", ".join(sorted({s.get("name", "?") for s in mcp_servers})) + ". Any request that names or "
           "refers to a specific board, page, document, or item that could live in one of them — \"add X from "
           "Miro\", \"bring in Y\", \"what's on the Z board\", or just naming something that sounds like it "
           "could be a real board/page title — means you MUST actually call the matching tool(s) and read "
           "what comes back before writing your plan or your reply. Search/list first if you're not sure of "
           "an exact id, then fetch that specific item's real content. NEVER substitute a generic placeholder "
           "instead — e.g. a single shape or sticky just labeled \"Miro board\" or describing what a "
           "whiteboard tool generally is, without any of the item's actual real content, is always wrong and "
           "is never an acceptable response to this kind of request, even as a fallback. If a question just "
           "asks what's on something (no drawing requested), still call the tool(s) to find out, then answer "
           "with the real content in \"reply\" and leave pull/create/connections/recolor empty, same as any "
           "other question. Once you have the real content, you have its actual widget/item type from the "
           "tool result itself — this is real structured data, not a photo to guess at — so use that type "
           "directly rather than defaulting everything to one kind: an actual sticky-note-type item becomes "
           "\"sticky\"; an actual shape/rectangle/geometric item becomes \"create\" kind=shape (category Basic, "
           "the closest real shapeKey — rectangle, circle, diamond, etc. — to what it actually is), carrying "
           "over its real text as the shape's label; a named, well-defined thing of a real BDCore type still "
           "becomes a \"concept\" regardless of its Miro widget type. The tool result also carries each item's "
           "real position (x/y, however that source names them) — set \"x\" and \"y\" on every item you create "
           "from it to that real position, so the layout you recreate here actually resembles the source "
           "instead of every item landing in an arbitrary row. For kind=shape specifically, when that same "
           "position data also carries a real width/height for the matching element, set the create item's own "
           "\"width\" and \"height\" to that too — a large frame and a small box need to stay different sizes "
           "relative to each other, not both collapse to the same default size; leaving width/height out is only "
           "correct when the source genuinely has no size data for that element. Only if a tool call genuinely errors, or "
           "nothing you found actually matches what was asked for, say so plainly in \"reply\" instead — never "
           "invent content and never create a generic stand-in object to paper over not having checked." if mcp_tools else "")
        + ("\n\nThis chat also has the following skill(s) added to it — reusable instructions an admin defined "
           "for exactly this kind of request, each named so you know when it applies. When the current request "
           "matches what a skill below describes, follow its instruction as part of building your plan and reply, "
           "using the same pull/create/connections/recolor mechanics described above — a skill only changes HOW "
           "you approach a matching request, never what you're allowed to do. If no active skill's description "
           "matches this particular request, ignore all of them and proceed normally.\n\n"
           + "\n\n".join(f"Skill \"{s['name']}\": {s['prompt']}" for s in active_skills) if active_skills else "")
    )

    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": request_text})
    plan, raw_plan, total_usage = get_validated_plan(
        plan_system, messages, tools=tools, tool_executor=tool_executor,
        # query_portfolio is now offered on every request (not just when an
        # MCP server is connected), so tool use is the default path here,
        # not a special case — always give it room to both read real data
        # and write out a full create[] array reproducing/reasoning about
        # it. Without this, a reply with more than a handful of items
        # reliably gets cut off mid-JSON and fails to parse on both
        # attempts, surfacing as a flat "I wasn't able to put together a
        # response for that" with no indication it was a length problem.
        max_tokens=4096,
        # Reaching real content through an MCP server like Miro's can take
        # several tool calls on its own (its workflow is: fetch a format
        # skill, fetch it again with a chosen step, search to narrow scope,
        # then finally read) before Claude has even seen what it's meant to
        # recreate — give that path extra headroom; a pure query_portfolio
        # flow (pull real data, reason, answer) rarely needs more than a
        # handful of rounds.
        max_tool_rounds=10 if mcp_tools else 6,
        model=high_model,
    )

    if plan is None:
        return jsonify({"error": "I wasn't able to put together a response for that — please try asking again.",
                         "raw": raw_plan,
                         "tokens": usage_with_total(total_usage)}), 200

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

    print(f"[canvas-chat: {request_text[:60]!r}] tokens — {usage_log_str(total_usage)}")
    if mcp_tools:
        positioned = [(c.get("tempId"), c.get("x"), c.get("y")) for c in plan.get("create", []) if isinstance(c.get("x"), (int, float))]
        unpositioned = [c.get("tempId") for c in plan.get("create", []) if not isinstance(c.get("x"), (int, float))]
        print(f"[canvas-chat: mcp plan] create items with x/y: {positioned} — without: {unpositioned}")

    pull_status = describe_pull_outcome(plan.get("pull"), pulled)
    model_reply = plan.get("reply", "").strip()
    reply = f"{pull_status} {model_reply}".strip() if pull_status else model_reply

    response = {
        "reply": reply,
        "pulled": pulled,
        "create": plan.get("create", []),
        "connections": plan.get("connections", []),
        "recolor": plan.get("recolor", []),
        "tokens": usage_with_total(total_usage),
    }
    if refreshed_auths:
        response["refreshedAuth"] = refreshed_auths
    return jsonify(response)


@app.route("/canvas-interpret", methods=["POST", "OPTIONS"])
def canvas_interpret():
    """
    The unstructured-data entry point /canvas-chat alone doesn't reach:
    reads an image (a photo or screenshot of a whiteboard, a Miro/Mural-style
    board, a hand-drawn diagram) or pasted text (a Confluence page, meeting
    notes, a requirements doc) and proposes a plan to represent what it
    finds as real BDCore concepts, stickies, and shapes — landing as
    unpushed drafts on the canvas, same as /canvas-chat's own "create", for
    a person to review before anything is real. Reuses the exact same plan
    shape and create/pull rules (plan_create_guidance) so the dashboard
    executes the result with the exact same executeCanvasPlan code, unchanged
    — this endpoint only differs in what it reads and how it's prompted, not
    in what it's allowed to produce or how that gets applied.

    One-shot by design, unlike /canvas-chat: there's no running conversation
    to have about a single image or document, so no history is accepted and
    there's no "recolor" (nothing exists yet to recolor) or the dual-case
    "reply" (question vs. drawing) logic /canvas-chat needs for its own
    back-and-forth chat thread.
    """
    if request.method == "OPTIONS":
        return "", 204

    image_data_url = (request.json.get("image") or "").strip()
    pasted_text = (request.json.get("text") or "").strip()
    source_label = (request.json.get("sourceLabel") or "").strip()
    if not image_data_url and not pasted_text:
        return jsonify({"error": "No image or text provided"}), 400
    _, high_model = resolve_models(request.json)

    canvas_snapshot = request.json.get("canvas", [])
    custom_palettes = request.json.get("customPalettes", [])
    schema_context, valid_rel_types = build_schema_context()
    source_desc = f' ("{source_label}")' if source_label else ""

    content_blocks = []
    if image_data_url:
        media_type, b64_data = parse_data_url(image_data_url)
        if not media_type:
            return jsonify({"error": "That image can't be read for interpretation — Claude's vision "
                                      "input only accepts JPEG, PNG, GIF, or WEBP (not SVG)."}), 400
        task_intro = (
            f"You are looking at an image{source_desc} — a photo or screenshot of a "
            "whiteboard, a Miro/Mural-style board, a hand-drawn diagram, or similar — and "
            "converting what's actually depicted in it into real BDCore concepts, "
            "stickies, and shapes on a visual canvas. This is a one-shot extraction, not a "
            "conversation: read everything legible in the image — boxes, sticky notes, "
            "labels, groupings, and any arrows or lines connecting them — and propose a "
            "plan that captures it faithfully. Don't invent anything that isn't reasonably "
            "inferable from what's actually in the image."
        )
        content_blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_data}})
        content_blocks.append({"type": "text", "text": "Read this image and propose the plan described in your instructions."})
    else:
        task_intro = (
            f"You are reading pasted text{source_desc} — a Confluence page, meeting "
            "notes, a requirements doc, or similar — and converting what it describes "
            "into real BDCore concepts, stickies, and shapes on a visual canvas. This is "
            "a one-shot extraction, not a conversation: identify the distinct entities, "
            "ideas, and relationships the text actually describes, and propose a plan "
            "that captures them faithfully. Don't invent anything the text doesn't "
            "support."
        )
        content_blocks.append({"type": "text", "text": pasted_text})

    plan_system = (
        task_intro + "\n\nRespond with ONLY a JSON object — no markdown fences, no "
        "explanation before or after — matching exactly this shape:\n\n"
        "{\n"
        '  "reply": "1-3 sentences describing what you found and created — named '
        'concepts, shapes, or stickies, and how they connect. If the source is too '
        'unclear or illegible to confidently extract anything, say so plainly here and '
        'leave pull/create/connections empty rather than guessing.",\n'
        '  "pull": [ { "cypher": "a real Cypher query, schema-validated, that RETURNS '
        'id, name, and a literal type string per match, e.g. RETURN c.id AS id, c.name '
        'AS name, \\"Capability\\" AS type — use this when something depicted plausibly '
        'already exists in the real portfolio, instead of creating a duplicate draft" } ],\n'
        '  "create": [\n'
        '    { "tempId": "n1", "kind": "concept", "conceptType": "<real concept type>", '
        '"name": "...", "attributes": { "<real attribute name>": "<value>" }, "x": <optional number>, "y": <optional number> },\n'
        '    { "tempId": "n2", "kind": "shape", "category": "<Basic|Cloud|Network|Security|'
        'Generic|BPM, OR an installed custom pack\'s own id — see below>", "shapeKey": '
        '"<real shape key — a built-in one below, or an installed custom pack\'s own icon key>", "label": "...", '
        '"x": <optional number>, "y": <optional number> },\n'
        '    { "tempId": "n3", "kind": "sticky", "text": "...", "x": <optional number>, "y": <optional number> }\n'
        "  ],\n"
        '  "connections": [\n'
        '    { "from": "<tempId, or pull:QUERY_INDEX:ROW_INDEX for a pulled entity>", '
        '"to": "<same>", "kind": "concept", "verb": "<only for kind=concept — a real '
        'verb valid for that exact type pair>" },\n'
        '    { "from": "...", "to": "...", "kind": "shape", "label": "<only for '
        'kind=shape — any free text, or omit>" }\n'
        "  ]\n"
        "}\n\n"
        "There is no \"recolor\" option here — nothing exists on the canvas yet for this "
        "extraction to recolor, so always leave it out entirely. Use \"sticky\" for "
        "anything that reads as an informal note or idea rather than a named, governed "
        "entity — most sticky-note-shaped things on a Miro-style board belong here, not "
        "as a \"concept\". Only promote something to a real \"concept\" when it's clearly a "
        "named, well-defined thing of a real BDCore type (an application, a capability, a "
        "process, etc). When genuinely unsure, prefer \"sticky\" — it's a far easier "
        "correction for a person to promote a sticky into a concept afterwards than to "
        "untangle an over-eager wrong concept.\n\n"
        + plan_create_guidance(schema_context, canvas_snapshot, custom_palettes)
    )

    messages = [{"role": "user", "content": content_blocks}]
    plan, raw_plan, total_usage = get_validated_plan(plan_system, messages, max_tokens=3072, model=high_model)

    if plan is None:
        return jsonify({"error": "I wasn't able to read that into a plan — please try again.",
                         "raw": raw_plan,
                         "tokens": usage_with_total(total_usage)}), 200

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

    print(f"[canvas-interpret: {source_label or ('image' if image_data_url else 'pasted text')}] "
          f"tokens — {usage_log_str(total_usage)}")

    pull_status = describe_pull_outcome(plan.get("pull"), pulled)
    model_reply = plan.get("reply", "").strip()
    reply = f"{pull_status} {model_reply}".strip() if pull_status else model_reply

    return jsonify({
        "reply": reply,
        "pulled": pulled,
        "create": plan.get("create", []),
        "connections": plan.get("connections", []),
        "recolor": [],
        "tokens": usage_with_total(total_usage),
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
    low_model, _ = resolve_models(request.json)

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
    raw, usage = call_claude(system, [{"role": "user", "content": req_text}], max_tokens=400, model=low_model)
    total_usage = empty_usage()
    add_usage(total_usage, usage)
    total_usage = usage_with_total(total_usage)

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


MCP_PROTOCOL_VERSION = "2025-03-26"


def _mcp_parse_response(resp):
    """
    An MCP Streamable-HTTP server may answer a POST with a single JSON
    object, or with an SSE stream of `data: {...}` events (the spec allows
    either) — this normalizes both into a list of JSON-RPC messages.
    """
    if "text/event-stream" in resp.headers.get("content-type", ""):
        messages = []
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    messages.append(json.loads(line[len("data:"):].strip()))
                except ValueError:
                    pass
        return messages
    try:
        return [resp.json()]
    except ValueError:
        return []


def mcp_request(url, token, method, params, session_id=None):
    """
    Sends one JSON-RPC 2.0 request (or, for a "notifications/..." method, a
    fire-and-forget notification) to a remote MCP server over the
    Streamable-HTTP transport. Returns (result, session_id) — session_id is
    whatever the server handed back via the Mcp-Session-Id response header,
    carried forward for the next call in the same handshake.
    """
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    is_notification = method.startswith("notifications/")
    body = {"jsonrpc": "2.0", "method": method, "params": params}
    if not is_notification:
        body["id"] = str(uuid.uuid4())

    resp = requests.post(url, json=body, headers=headers, timeout=20)
    resp.raise_for_status()
    new_session_id = resp.headers.get("Mcp-Session-Id") or session_id
    if is_notification or resp.status_code == 202:
        return None, new_session_id

    for msg in _mcp_parse_response(resp):
        if msg.get("id") == body.get("id"):
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", "The MCP server returned an error"))
            return msg.get("result"), new_session_id
    return None, new_session_id


def mcp_handshake(url, token):
    """
    Every /mcp/* request here opens (and discards) a brand-new MCP session
    rather than persisting one across requests — this is a stateless Flask
    handler with no per-browser-tab session store, and re-initializing each
    time is cheap next to the complexity of caching one server-side.
    """
    _, session_id = mcp_request(url, token, "initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "bdcore", "version": "1.0"},
    })
    mcp_request(url, token, "notifications/initialized", {}, session_id=session_id)
    return session_id


def _refresh_oauth_token(auth):
    resp = requests.post(auth["tokenEndpoint"], data={
        "grant_type": "refresh_token",
        "refresh_token": auth["refreshToken"],
        "client_id": auth["clientId"],
    }, headers={"Accept": "application/json"}, timeout=10)
    resp.raise_for_status()
    tokens = resp.json()
    return {
        "type": "oauth",
        "accessToken": tokens.get("access_token"),
        "refreshToken": tokens.get("refresh_token") or auth["refreshToken"],
        "expiresAt": time.time() * 1000 + tokens.get("expires_in", 3600) * 1000,
        "tokenEndpoint": auth["tokenEndpoint"],
        "clientId": auth["clientId"],
    }


def resolve_token(auth):
    """
    Turns whatever auth shape the frontend sent — none, a plain static
    token, or an OAuth token that may need refreshing first — into the
    bearer token value to actually send. Returns (token, refreshed_auth);
    refreshed_auth is only non-None when a refresh just happened, so the
    caller can hand the new tokens back to the frontend to persist (this
    backend keeps no state between requests beyond an in-flight OAuth
    handshake — see _oauth_pending below).
    """
    if not auth:
        return None, None
    if auth.get("type") == "bearer":
        return (auth.get("token") or None), None
    if auth.get("type") == "oauth":
        if time.time() * 1000 < (auth.get("expiresAt") or 0) - 60_000:
            return auth.get("accessToken"), None
        refreshed = _refresh_oauth_token(auth)
        return refreshed["accessToken"], refreshed
    return None, None


MAX_TOOL_RESULT_CHARS = 8000

PULL_TOOL_NAME = "query_portfolio"
PULL_TOOL = {
    "name": PULL_TOOL_NAME,
    "description": (
        "Run a real, read-only Cypher query against the live portfolio graph and see its actual results "
        "before you decide what to say or draw. Use this whenever a request needs you to reason about real "
        "data — overlap between applications, an application's actual business value/technical health/"
        "hosting, what supports a capability, dependency or risk impact — instead of writing a blind guess. "
        "This only lets you SEE data for your own reasoning; it does not by itself put anything on the "
        "canvas. If the real entities you find here should also appear on the canvas for the person to see, "
        "still add them to your final plan's own \"pull\" array the normal way — this tool and that field "
        "serve different purposes and often both apply to the same request."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cypher": {
                "type": "string",
                "description": "A real, read-only Cypher query (RETURN only — no CREATE/MERGE/DELETE/SET/REMOVE/DROP), "
                                "using only relationship types and properties that actually exist per the schema you were given.",
            },
        },
        "required": ["cypher"],
    },
}


def make_pull_tool_executor(valid_rel_types):
    """
    The tool_executor for PULL_TOOL — validates the model's Cypher the same
    way an actual "pull" entry already is (find_invalid_relationship_types)
    before running it, so a live mid-turn query is held to the same bar as
    the existing post-hoc one, then returns the real rows as JSON. Reuses
    run_cypher, which is itself the one place read-only is now enforced.
    """
    def executor(tool_name, arguments):
        if tool_name != PULL_TOOL_NAME:
            return f"Unknown tool {tool_name!r}.", True
        cypher = (arguments or {}).get("cypher", "")
        invalid = find_invalid_relationship_types(cypher, valid_rel_types)
        if invalid:
            return f"This query uses relationship type(s) {invalid} which don't exist in this schema. Valid relationship types are only: {sorted(valid_rel_types)}", True
        try:
            rows = run_cypher(cypher)
        except Exception as e:
            return f"Query failed: {e}", True
        text = json.dumps(rows, default=str)
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "... [truncated]"
        print(f"[pull-tool-call] cypher={cypher!r} rows={len(rows)}")
        return text, False
    return executor


def mcp_tools_to_anthropic(mcp_servers):
    """
    Maps each connected MCP server's already-discovered tools (the frontend
    sends whatever it has cached from its own "Test"/"Browse tools" calls —
    this never does a fresh tools/list itself) onto real Anthropic tool
    definitions, so canvas-chat's Claude can decide for itself when a
    request needs to reach one of them ("bring in X from Miro") instead of
    us trying to pattern-match server names out of the request text. An MCP
    tool's inputSchema is already JSON Schema, so it's reused verbatim as
    Anthropic's own input_schema rather than translated.

    Returns (anthropic_tools, lookup) where lookup maps each generated
    Anthropic tool name back to (server_dict, real_mcp_tool_name), since
    Anthropic tool names must be unique across every connected server.
    """
    anthropic_tools = []
    lookup = {}
    for server in mcp_servers or []:
        for tool in server.get("tools") or []:
            name = tool.get("name")
            if not name or not server.get("url"):
                continue
            anthropic_name = f"mcp__{server['id']}__{name}"[:128]
            lookup[anthropic_name] = (server, name)
            anthropic_tools.append({
                "name": anthropic_name,
                "description": f'[Connected MCP server "{server.get("name", "?")}"] {tool.get("description") or ""}'.strip(),
                "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            })
    return anthropic_tools, lookup


_RENDERED_BOUNDS_TAG_RE = re.compile(r"<[a-zA-Z][^<>]*>")
_RENDERED_BOUNDS_ATTR_RES = {
    "miroId": re.compile(r'data-miro-id=\\*"([^"\\]*)'),
    "bounds": re.compile(r'data-rendered-bounds=\\*"([^"\\]*)'),
    "content": re.compile(r'data-content=\\*"([^"\\]*)'),
    "x": re.compile(r'\sx=\\*"([^"\\]*)'),
    "y": re.compile(r'\sy=\\*"([^"\\]*)'),
    "width": re.compile(r'\swidth=\\*"([^"\\]*)'),
    "height": re.compile(r'\sheight=\\*"([^"\\]*)'),
}


def _tag_box(tag):
    """
    An element's own box as (x, y, width, height) read directly from its
    native x/y/width/height attributes — correct ONLY for the top-left
    convention a <rect> actually uses per Miro's own canvas-composer spec
    (a circle/ellipse's cx/cy is already its center and a <text>'s y is a
    baseline, neither of which this covers). Returns None for anything else
    or when an attribute is missing/unparseable.
    """
    if not tag.startswith("<rect"):
        return None
    try:
        x = float(_RENDERED_BOUNDS_ATTR_RES["x"].search(tag).group(1))
        y = float(_RENDERED_BOUNDS_ATTR_RES["y"].search(tag).group(1))
        w = float(_RENDERED_BOUNDS_ATTR_RES["width"].search(tag).group(1))
        h = float(_RENDERED_BOUNDS_ATTR_RES["height"].search(tag).group(1))
    except (AttributeError, ValueError):
        return None
    return x, y, w, h


def extract_rendered_bounds(raw_result_text):
    """
    Best-effort extraction of each element's real center AND size straight
    out of a raw MCP tool result — asking Claude to reliably parse a whole
    SVG document's per-element geometry (which itself varies by tag:
    top-left for a rect, center for a circle, frame-relative when nested,
    ...) inline while also deciding what to create turned out to not be
    reliable in practice (confirmed over several rounds: a recreated board
    kept landing as a flat row indistinguishable from having no position
    data at all, even once the guidance named the exact right attribute).
    Doing the well-specified, unambiguous part in code removes that step
    from Claude's plate entirely, leaving it a lookup instead of an
    SVG-parsing-plus-arithmetic task.

    Size matters here as much as position: a large frame and a small box
    that both lose their real width/height collapse to the same default
    shape size on the canvas, which erases the "big thing containing small
    things" relationship a frame's children are usually drawn to show —
    recreating centers correctly but at uniform size still doesn't
    resemble the source.

    Two sources, tried in order per element: Miro's own
    data-rendered-bounds="x y width height" when present (already absolute,
    already normalized regardless of element type or frame nesting — but
    confirmed NOT always present, e.g. a canvas_read_as_svg of plain
    pre-existing content came back with none at all); otherwise a <rect>'s
    own native x/y/width/height, which is top-left per the DSL spec and was
    confirmed present on every element in that same real response. Anything
    else (a circle, an unmeasured non-rect) is left for Claude's own
    judgement, same as before this existed.

    Regex over the raw text (not real XML parsing) on purpose: the exact
    envelope shape around the SVG text varies by tool and is often
    JSON-escaped, so this never assumes a specific result shape, only the
    attributes themselves — anything that matches neither returns [], a
    safe no-op for any other MCP server's result.

    Deduplicated by miroId: a tool's own JSON envelope commonly mirrors the
    same SVG text in more than one field (e.g. once inside a content[].text
    JSON string and again in a structuredContent copy), which would
    otherwise report every element twice over.
    """
    out = []
    seen_ids = set()
    for tag in _RENDERED_BOUNDS_TAG_RE.findall(raw_result_text):
        id_match = _RENDERED_BOUNDS_ATTR_RES["miroId"].search(tag)
        if not id_match or id_match.group(1) in seen_ids:
            continue

        box = None
        bounds_match = _RENDERED_BOUNDS_ATTR_RES["bounds"].search(tag)
        if bounds_match:
            parts = bounds_match.group(1).split()
            if len(parts) == 4:
                try:
                    box = tuple(float(p) for p in parts)
                except ValueError:
                    box = None
        if box is None:
            box = _tag_box(tag)
        if box is None:
            continue
        x, y, w, h = box

        seen_ids.add(id_match.group(1))
        entry = {
            "miroId": id_match.group(1),
            "centerX": round(x + w / 2, 1), "centerY": round(y + h / 2, 1),
            "width": round(w, 1), "height": round(h, 1),
        }
        content_match = _RENDERED_BOUNDS_ATTR_RES["content"].search(tag)
        if content_match:
            entry["content"] = content_match.group(1)
        out.append(entry)
    return out


def make_mcp_tool_executor(lookup, refreshed_auths):
    """
    Builds the tool_executor callback get_validated_plan's tool-use loop
    calls for each tool_use block — looks up which real server/tool an
    Anthropic tool name maps to and actually calls it, reusing the exact
    same resolve_token/mcp_handshake/mcp_request machinery as /mcp/call.
    refreshed_auths (a dict the caller owns) collects any OAuth token
    refreshed along the way, keyed by server id, so the route handler can
    hand them all back to the frontend to persist at the end.
    """
    def executor(anthropic_tool_name, arguments):
        entry = lookup.get(anthropic_tool_name)
        if not entry:
            return f"Unknown tool {anthropic_tool_name!r}.", True
        server, tool_name = entry
        try:
            token, refreshed = resolve_token(server.get("auth"))
            if refreshed:
                refreshed_auths[server["id"]] = refreshed
            session_id = mcp_handshake(server["url"], token)
            result, _ = mcp_request(server["url"], token, "tools/call", {"name": tool_name, "arguments": arguments}, session_id=session_id)
            text = json.dumps(result)

            # Reserved separately from the raw-text budget below so a large
            # board's SVG getting truncated never also costs the one piece
            # of this result most worth keeping intact.
            extracted = extract_rendered_bounds(text)
            summary = ""
            if extracted:
                summary = ("\n\n[Extracted absolute center positions and real sizes, already computed "
                           "server-side from each element's own geometry — use centerX/centerY directly as a "
                           "\"create\" item's x/y for the matching miroId, instead of parsing the raw SVG "
                           "geometry yourself; for kind=shape items also copy width/height directly across the "
                           "same way, so a large element doesn't shrink to the same size as a small one]: "
                           + json.dumps(extracted))

            budget = max(MAX_TOOL_RESULT_CHARS - len(summary), 1000)
            if len(text) > budget:
                text = text[:budget] + "... [truncated]"
            # Printed rather than silently trusted: every attempt at this
            # specific feature (layout fidelity recreating an MCP-fetched
            # board) that looked right in isolation has still failed against
            # the real server, with nothing in this file saying what Claude
            # actually called or saw — this is the one place that can show
            # whether it called the right tool, with what arguments, and
            # whether there was any position data in the result to find.
            print(f"[mcp-tool-call] {tool_name!r} on {server.get('name', '?')!r} args={arguments} "
                  f"result_len={len(text)} rendered_bounds_found={len(extracted)} extracted={extracted}")
            return text + summary, False
        except Exception as e:
            return f'Error calling "{tool_name}" on "{server.get("name", "?")}": {e}', True
    return executor


@app.route("/mcp/tools", methods=["POST", "OPTIONS"])
def mcp_tools():
    """
    Connects to a user-configured MCP server (Miro, or any other) and lists
    its available tools, so the Integrations panel can show what's actually
    callable instead of the dashboard having to hard-code any one server's
    API shape.
    """
    if request.method == "OPTIONS":
        return "", 204

    url = (request.json.get("url") or "").strip()
    auth = request.json.get("auth")
    if not url:
        return jsonify({"ok": False, "error": "No server URL provided"}), 200

    try:
        token, refreshed = resolve_token(auth)
        session_id = mcp_handshake(url, token)
        result, _ = mcp_request(url, token, "tools/list", {}, session_id=session_id)
        resp = {"ok": True, "tools": (result or {}).get("tools", [])}
        if refreshed:
            resp["refreshedAuth"] = refreshed
        return jsonify(resp)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/mcp/call", methods=["POST", "OPTIONS"])
def mcp_call():
    """
    Calls one tool on a user-configured MCP server and hands back its raw
    result — deliberately generic (any tool, any arguments) rather than
    Miro-specific, so the same endpoint serves whatever MCP server gets
    connected next.
    """
    if request.method == "OPTIONS":
        return "", 204

    url = (request.json.get("url") or "").strip()
    auth = request.json.get("auth")
    tool_name = (request.json.get("tool") or "").strip()
    args = request.json.get("args") or {}
    if not url or not tool_name:
        return jsonify({"ok": False, "error": "Server URL and tool name are required"}), 200
    if not isinstance(args, dict):
        return jsonify({"ok": False, "error": "Tool arguments must be a JSON object"}), 200

    try:
        token, refreshed = resolve_token(auth)
        session_id = mcp_handshake(url, token)
        result, _ = mcp_request(url, token, "tools/call", {"name": tool_name, "arguments": args}, session_id=session_id)
        resp = {"ok": True, "result": result}
        if refreshed:
            resp["refreshedAuth"] = refreshed
        return jsonify(resp)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


# ---------------------------------------------------------------------------
# MCP OAuth 2.1 (Authorization Code + PKCE, dynamic client registration) —
# only needed for a server that rejects a plain static bearer token, Miro's
# official MCP server among them. This runs the browser-redirect dance on
# the dashboard's behalf (per the MCP authorization spec's discovery chain:
# RFC 9728 protected-resource metadata -> RFC 8414 authorization-server
# metadata -> RFC 7591 dynamic client registration -> PKCE auth-code
# exchange) and hands the resulting tokens back to the open dashboard tab
# via a postMessage from a small callback page, since that's the only
# channel a popup has back to its opener. _oauth_pending holds an
# in-flight handshake's state only until its callback arrives — nothing
# here outlives the exchange, consistent with this backend never
# persisting a credential.
# ---------------------------------------------------------------------------
REDIRECT_BASE = "http://localhost:5050"
_oauth_pending = {}


def _well_known_fetch(url):
    try:
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def oauth_discover(mcp_url):
    parsed = urlparse(mcp_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    prm = _well_known_fetch(f"{origin}/.well-known/oauth-protected-resource")
    if prm is None and parsed.path not in ("", "/"):
        prm = _well_known_fetch(f"{origin}/.well-known/oauth-protected-resource{parsed.path}")
    if not prm or not prm.get("authorization_servers"):
        raise RuntimeError(
            "This server didn't publish OAuth protected-resource metadata — it may not "
            "support OAuth at all, or may need a plain access token instead (use the "
            "\"Access token\" field above)."
        )

    issuer = prm["authorization_servers"][0].rstrip("/")
    asm = (_well_known_fetch(f"{issuer}/.well-known/oauth-authorization-server")
           or _well_known_fetch(f"{issuer}/.well-known/openid-configuration"))
    if not asm:
        raise RuntimeError(f"Couldn't read the authorization server's metadata at {issuer}.")
    for key in ("authorization_endpoint", "token_endpoint"):
        if key not in asm:
            raise RuntimeError(f"The authorization server's metadata is missing {key}.")
    return {
        "authorization_endpoint": asm["authorization_endpoint"],
        "token_endpoint": asm["token_endpoint"],
        "registration_endpoint": asm.get("registration_endpoint"),
    }


def oauth_register_client(registration_endpoint, redirect_uri):
    if not registration_endpoint:
        raise RuntimeError(
            "This authorization server doesn't support dynamic client registration — it "
            "needs a pre-registered app instead, which isn't something this page can set up."
        )
    resp = requests.post(registration_endpoint, json={
        "redirect_uris": [redirect_uri],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "BDCore",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["client_id"]


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _oauth_popup_close_page(ok, server_url=None, tokens=None, error=None):
    """
    The page the OAuth popup lands on at the very end of the dance — hands
    the result back to the dashboard tab via postMessage (the only channel
    a popup has back to its opener) and closes itself, rather than leaving
    a stray tab open with nothing to do.
    """
    payload = json.dumps({
        "type": "bdcore-mcp-oauth", "ok": ok, "serverUrl": server_url,
        "tokens": tokens, "error": error,
    }).replace("</script>", "<\\/script>")
    message = f"Couldn't connect: {error}" if (not ok and error) else "Connected — this window will close automatically."
    color = "#F0384D" if not ok else "#0A0E1A"
    delay_ms = 4000 if not ok else 1200
    return f"""<!doctype html><html><body style="font-family:sans-serif;padding:24px;color:{color}">
<p>{html.escape(message)}</p>
<script>
  if (window.opener) {{ window.opener.postMessage({payload}, "*"); }}
  setTimeout(() => window.close(), {delay_ms});
</script>
</body></html>"""


@app.route("/mcp/oauth/start", methods=["GET"])
def mcp_oauth_start():
    mcp_url = (request.args.get("url") or "").strip()
    if not mcp_url:
        return "Missing ?url=", 400
    redirect_uri = f"{REDIRECT_BASE}/mcp/oauth/callback"
    try:
        endpoints = oauth_discover(mcp_url)
        client_id = oauth_register_client(endpoints["registration_endpoint"], redirect_uri)
    except Exception as e:
        return _oauth_popup_close_page(ok=False, error=str(e))

    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    _oauth_pending[state] = {
        "mcp_url": mcp_url, "client_id": client_id, "code_verifier": verifier,
        "token_endpoint": endpoints["token_endpoint"], "created": time.time(),
    }
    auth_url = endpoints["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return redirect(auth_url)


@app.route("/mcp/oauth/callback", methods=["GET"])
def mcp_oauth_callback():
    state = request.args.get("state") or ""
    pending = _oauth_pending.pop(state, None)
    error = request.args.get("error")
    if error:
        return _oauth_popup_close_page(ok=False, error=request.args.get("error_description") or error)
    if not pending:
        return _oauth_popup_close_page(ok=False, error="This authorization link expired or was already used — try connecting again.")

    try:
        resp = requests.post(pending["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": request.args.get("code"),
            "redirect_uri": f"{REDIRECT_BASE}/mcp/oauth/callback",
            "client_id": pending["client_id"],
            "code_verifier": pending["code_verifier"],
        }, headers={"Accept": "application/json"}, timeout=10)
        resp.raise_for_status()
        tokens = resp.json()
    except Exception as e:
        return _oauth_popup_close_page(ok=False, error=f"Token exchange failed: {e}")

    return _oauth_popup_close_page(ok=True, server_url=pending["mcp_url"], tokens={
        "accessToken": tokens.get("access_token"),
        "refreshToken": tokens.get("refresh_token"),
        "expiresIn": tokens.get("expires_in"),
        "tokenEndpoint": pending["token_endpoint"],
        "clientId": pending["client_id"],
    })


if __name__ == "__main__":
    print("Chat backend running at http://localhost:5050")
    app.run(port=5050, debug=False)
