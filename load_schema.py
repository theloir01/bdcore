"""
BDCore schema loader.

Reads bdcore_schema.yaml and creates the ontology's SCHEMA LAYER in Neo4j:
  - ConceptType nodes (the concepts: Strategy, Goal, Capability, etc.)
  - AttributeDefinition nodes, linked to their ConceptType via HAS_ATTRIBUTE
  - RelationshipType nodes (the verb/source/target combinations), linked
    to their source and target ConceptTypes via HAS_SOURCE / HAS_TARGET
  - A single RelationshipAttributeSet node holding the 4 universal
    relationship attributes (Criticality, Status, Strength, Type)

Every run clears the existing schema layer first, then rebuilds it fresh
from the YAML — not just adding what's new, but also removing anything
that's no longer in the file (a retired concept type or relationship verb).
Earlier versions of this script only merged, never removed, which let stale
schema nodes linger silently after an edit — exactly the kind of thing an
AI reading the schema can't tell apart from something genuinely still valid.
This only ever touches ConceptType/AttributeDefinition/RelationshipType/
RelationshipAttributeSet nodes — it never touches :Instance nodes, so your
real enterprise data (actual capabilities, applications, etc.) is completely
unaffected by re-running this.
"""

import yaml
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# EDIT THESE THREE VALUES — copy them from your Aura instance's connection
# details (the ones you downloaded when you created the Free instance).
# ---------------------------------------------------------------------------
NEO4J_URI = "neo4j+s://745d653e.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "9iizTzGOGMw6EvEgVyeohXpeufJgnHgN_ExQblJpe_k"
# ---------------------------------------------------------------------------

SCHEMA_FILE = "bdcore_schema.yaml"


def flatten_attributes(raw_attrs):
    """
    In the YAML, each concept's attribute list starts with a YAML anchor
    reference to base_attributes, which is itself a list. That means the
    parsed Python list looks like: [ [base_attr_dicts...], {attr}, {attr}, ... ]
    This flattens that one level so we get a clean flat list of attribute dicts.
    """
    flat = []
    for item in raw_attrs:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return flat


def load_schema_file(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


def clear_schema_layer(tx):
    # Scoped precisely to the 4 schema-layer labels — deliberately does NOT
    # touch anything labeled :Instance, so real enterprise data is never at
    # risk here regardless of what changed in the YAML.
    tx.run("MATCH (n:ConceptType) DETACH DELETE n")
    tx.run("MATCH (n:AttributeDefinition) DETACH DELETE n")
    tx.run("MATCH (n:RelationshipType) DETACH DELETE n")
    tx.run("MATCH (n:RelationshipAttributeSet) DETACH DELETE n")


def create_constraints(tx):
    tx.run(
        "CREATE CONSTRAINT concept_type_name IF NOT EXISTS "
        "FOR (c:ConceptType) REQUIRE c.name IS UNIQUE"
    )
    tx.run(
        "CREATE CONSTRAINT relationship_type_key IF NOT EXISTS "
        "FOR (r:RelationshipType) REQUIRE r.key IS UNIQUE"
    )


def create_concept_types(tx, concept_types):
    for concept in concept_types:
        tx.run(
            """
            MERGE (c:ConceptType {name: $name})
            SET c.category = $category
            """,
            name=concept["name"],
            category=concept.get("category"),
        )

        attrs = flatten_attributes(concept["attributes"])
        for attr in attrs:
            tx.run(
                """
                MERGE (a:AttributeDefinition {
                    concept_type: $concept_name,
                    name: $attr_name
                })
                SET a.type = $attr_type,
                    a.options = $options,
                    a.required = $required,
                    a.unit = $unit
                WITH a
                MATCH (c:ConceptType {name: $concept_name})
                MERGE (c)-[:HAS_ATTRIBUTE]->(a)
                """,
                concept_name=concept["name"],
                attr_name=attr["name"],
                attr_type=attr.get("type"),
                options=attr.get("options"),
                required=attr.get("required", False),
                unit=attr.get("unit"),
            )


def create_relationship_types(tx, relationship_types):
    for rel in relationship_types:
        key = f'{rel["source"]}::{rel["verb"]}::{rel["target"]}'
        tx.run(
            """
            MERGE (r:RelationshipType {key: $key})
            SET r.verb = $verb,
                r.category = $category
            WITH r
            MATCH (s:ConceptType {name: $source})
            MATCH (t:ConceptType {name: $target})
            MERGE (r)-[:HAS_SOURCE]->(s)
            MERGE (r)-[:HAS_TARGET]->(t)
            """,
            key=key,
            verb=rel["verb"],
            category=rel.get("category"),
            source=rel["source"],
            target=rel["target"],
        )


def create_universal_relationship_attributes(tx, universal_attrs):
    tx.run(
        """
        MERGE (u:RelationshipAttributeSet {name: 'universal'})
        SET u.attributes = $attrs
        """,
        attrs=[a["name"] for a in universal_attrs],
    )


def main():
    print(f"Reading schema from {SCHEMA_FILE}...")
    data = load_schema_file(SCHEMA_FILE)

    concept_types = data["concept_types"]
    relationship_types = data["relationship_types"]
    universal_attrs = data["relationship_universal_attributes"]

    print(f"Found {len(concept_types)} concept types.")
    print(f"Found {len(relationship_types)} relationship types.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

    try:
        driver.verify_connectivity()
        print("Connected to Neo4j successfully.")
    except Exception as e:
        print("Could not connect to Neo4j. Check your URI/username/password.")
        print(f"Error: {e}")
        return

    with driver.session() as session:
        print("Clearing existing schema layer (ConceptType/AttributeDefinition/RelationshipType) — instance data is untouched...")
        session.execute_write(clear_schema_layer)

        print("Creating constraints...")
        session.execute_write(create_constraints)

        print("Creating concept types and attributes...")
        session.execute_write(create_concept_types, concept_types)

        print("Creating relationship types...")
        session.execute_write(create_relationship_types, relationship_types)

        print("Creating universal relationship attribute set...")
        session.execute_write(
            create_universal_relationship_attributes, universal_attrs
        )

    driver.close()
    print("\nDone. Your BDCore schema is now in Neo4j.")
    print("Open the Aura console's Query tab and try:")
    print("  MATCH (c:ConceptType) RETURN c")
    print("  MATCH (r:RelationshipType)-[:HAS_SOURCE|HAS_TARGET]-(c) RETURN r, c LIMIT 50")


if __name__ == "__main__":
    main()
