"""
BDCore instance loader — Royal British Legion demo dataset.

Reads bdcore_rbl_instances.yaml and creates the INSTANCE LAYER in Neo4j:
  - one node per instance, labelled with its concept type (e.g. :Capability)
    plus a generic :Instance label for uniform lookups
  - each instance node linked to its ConceptType schema node via INSTANCE_OF,
    so you can always trace an instance back to the ontology definition it
    belongs to
  - relationship edges between instances, using the verb as the Neo4j
    relationship type (sanitised — spaces become underscores, uppercased),
    carrying the four universal attributes (Criticality, Status, Strength,
    Type) as edge properties

Run load_schema.py FIRST — this script assumes ConceptType nodes already
exist and will fail fast if they don't.

Idempotent: safe to re-run after editing the YAML.
"""

import re
import yaml
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# EDIT THESE THREE VALUES — same as load_schema.py
# ---------------------------------------------------------------------------
NEO4J_URI = "neo4j+s://745d653e.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "9iizTzGOGMw6EvEgVyeohXpeufJgnHgN_ExQblJpe_k"
# ---------------------------------------------------------------------------

INSTANCE_FILE = "bdcore_rbl_instances.yaml"


def sanitise_rel_type(verb):
    """Turn a verb like 'approves investment in' into APPROVES_INVESTMENT_IN."""
    return re.sub(r"[^A-Za-z0-9]+", "_", verb.strip()).strip("_").upper()


def load_instance_file(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def create_node_constraint(tx):
    tx.run(
        "CREATE CONSTRAINT instance_id IF NOT EXISTS "
        "FOR (n:Instance) REQUIRE n.id IS UNIQUE"
    )


def create_nodes(tx, nodes):
    for node in nodes:
        concept_type = node["concept_type"]
        node_id = node["id"]
        # everything except id/concept_type is a business attribute
        props = {k: v for k, v in node.items() if k not in ("id", "concept_type")}

        # dynamic label — concept_type names are controlled (from our own
        # schema file), safe to interpolate directly into the Cypher label
        tx.run(
            f"""
            MERGE (n:Instance:{concept_type} {{id: $id}})
            SET n += $props
            WITH n
            MATCH (ct:ConceptType {{name: $concept_type}})
            MERGE (n)-[:INSTANCE_OF]->(ct)
            """,
            id=node_id,
            props=props,
            concept_type=concept_type,
        )


def create_relationships(tx, relationships):
    for rel in relationships:
        rel_type = sanitise_rel_type(rel["verb"])
        edge_props = {
            "verb": rel["verb"],
            "criticality": rel.get("criticality"),
            "status": rel.get("status"),
            "strength": rel.get("strength"),
            "type": rel.get("type"),
        }
        tx.run(
            f"""
            MATCH (a:Instance {{id: $source}})
            MATCH (b:Instance {{id: $target}})
            MERGE (a)-[r:{rel_type}]->(b)
            SET r += $props
            """,
            source=rel["source"],
            target=rel["target"],
            props=edge_props,
        )


def main():
    print(f"Reading instance data from {INSTANCE_FILE}...")
    data = load_instance_file(INSTANCE_FILE)

    nodes = data["nodes"]
    relationships = data["relationships"]
    print(f"Found {len(nodes)} instance nodes.")
    print(f"Found {len(relationships)} relationship instances.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
        print("Connected to Neo4j successfully.")
    except Exception as e:
        print("Could not connect to Neo4j. Check your URI/username/password.")
        print(f"Error: {e}")
        return

    with driver.session() as session:
        print("Creating instance constraint...")
        session.execute_write(create_node_constraint)

        print("Creating instance nodes (linked to their ConceptType)...")
        session.execute_write(create_nodes, nodes)

        print("Creating relationship instances...")
        session.execute_write(create_relationships, relationships)

    driver.close()
    print("\nDone. The Royal British Legion demo graph is loaded.")
    print("Try in the Aura Query tab:")
    print("  MATCH (n:Instance) RETURN n")
    print("  MATCH (n:Capability)-[r]-(m) RETURN n, r, m")
    print("  MATCH (r:Risk)-[e:AFFECTS]->(n) RETURN r, e, n")


if __name__ == "__main__":
    main()
