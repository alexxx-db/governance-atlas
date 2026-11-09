import json
import re
from pathlib import Path

import pytest

from axiom.services import genie_space_config as config

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "docs" / "genie" / "axiom-genie-agent.json"
HEX_ID = re.compile(r"^[0-9a-f]{32}$")
CATALOG = "ops_governance"


@pytest.fixture(scope="module")
def payload():
    return config.serialized_space_payload(catalog=CATALOG)


def _all_ids(payload):
    instructions = payload["instructions"]
    return {
        "sample_questions": [item["id"] for item in payload["config"]["sample_questions"]],
        "example_question_sqls": [item["id"] for item in instructions["example_question_sqls"]],
        "text_instructions": [item["id"] for item in instructions["text_instructions"]],
        "join_specs": [item["id"] for item in instructions["join_specs"]],
        "benchmarks": [item["id"] for item in payload["benchmarks"]["questions"]],
    }


def test_serialized_space_string_matches_payload(payload):
    assert json.loads(config.serialized_space(catalog=CATALOG)) == payload


def test_top_level_shape(payload):
    assert set(payload) == {"version", "config", "data_sources", "instructions", "benchmarks"}
    assert "benchmarks" not in payload["instructions"]


def test_ids_are_32_hex_unique_and_sorted(payload):
    every = []
    for name, ids in _all_ids(payload).items():
        assert ids, name
        assert all(HEX_ID.match(value) for value in ids), name
        assert len(ids) == len(set(ids)), name
        assert ids == sorted(ids), name
        every.extend(ids)
    assert len(every) == len(set(every))


def test_single_text_instruction_with_array_content(payload):
    instructions = payload["instructions"]["text_instructions"]
    assert len(instructions) == 1
    assert all(isinstance(line, str) and line for line in instructions[0]["content"])


def test_tables_and_columns_sorted(payload):
    tables = payload["data_sources"]["tables"]
    identifiers = [table["identifier"] for table in tables]
    assert identifiers == sorted(identifiers)
    assert {identifier.rsplit(".", 1)[-1] for identifier in identifiers} == set(config.curated_view_names())
    for table in tables:
        names = [column["column_name"] for column in table["column_configs"]]
        assert names == sorted(names)
        assert len(names) == len(set(names))


def test_column_configs_cover_every_view_column(payload):
    statements = {item["name"]: item["sql"] for item in config.curated_view_statements(catalog=CATALOG, store_schema="axiom_alex")}
    documented = {
        table["identifier"].rsplit(".", 1)[-1]: {column["column_name"] for column in table["column_configs"]}
        for table in payload["data_sources"]["tables"]
    }
    # Final-projection aliases in the views that build their column list explicitly.
    expected = {
        "axiom_ai_assets_current": {"asset_fqn", "catalog_name", "schema_name", "table_name", "table_type", "comment", "created", "last_altered", "domain", "tier", "certification", "sensitivity", "criticality", "data_product", "business_owners", "owner_count", "open_work_count", "has_owner", "is_certified", "is_critical"},
        "axiom_ai_governance_work_current": {"work_id", "work_type", "status", "asset_fqn", "title", "requested_tags_json", "created_by", "created_at", "reviewed_by", "reviewed_at", "review_note"},
        "axiom_ai_lineage_edges": {"source_asset_fqn", "target_asset_fqn", "lineage_source", "event_time", "availability_state"},
    }
    for view, columns in expected.items():
        assert columns == documented[view], view
        for column in columns:
            assert column in statements[view], (view, column)


def test_questions_and_sql_are_arrays(payload):
    for example in payload["instructions"]["example_question_sqls"]:
        assert isinstance(example["question"], list) and len(example["question"]) == 1
        assert isinstance(example["sql"], list) and example["sql"][0].strip()
        assert isinstance(example["usage_guidance"], list)
    for benchmark in payload["benchmarks"]["questions"]:
        assert isinstance(benchmark["question"], list) and len(benchmark["question"]) == 1
        assert benchmark["answer"][0]["format"] == "SQL"
        assert isinstance(benchmark["answer"][0]["content"], list)


def test_benchmarks_are_extensive_and_cover_every_example(payload):
    examples = {item["question"][0] for item in payload["instructions"]["example_question_sqls"]}
    benchmarks = [item["question"][0] for item in payload["benchmarks"]["questions"]]
    assert len(examples) >= 40
    assert len(benchmarks) >= 80
    assert len(benchmarks) == len(set(benchmarks))
    assert examples <= set(benchmarks)


def test_sample_questions_are_backed_by_examples(payload):
    examples = {item["question"][0] for item in payload["instructions"]["example_question_sqls"]}
    samples = [item["question"][0] for item in payload["config"]["sample_questions"]]
    assert len(samples) >= 10
    assert set(samples) <= examples


def _all_sql(payload):
    for example in payload["instructions"]["example_question_sqls"]:
        yield example["question"][0], "\n".join(example["sql"])
    for benchmark in payload["benchmarks"]["questions"]:
        yield benchmark["question"][0], "\n".join(benchmark["answer"][0]["content"])


def test_sql_only_reads_curated_views(payload):
    allowed = {config._fq(CATALOG, config.DEFAULT_AI_SCHEMA, name) for name in config.curated_view_names()}
    for question, sql in _all_sql(payload):
        referenced = set(re.findall(r"`[^`]+`\.`[^`]+`\.`[^`]+`", sql))
        assert referenced and referenced <= allowed, question
        assert "system." not in sql.lower(), question


def test_sql_has_no_sentinel_fallbacks(payload):
    for question, sql in _all_sql(payload):
        lowered = sql.lower()
        assert "union" not in lowered, question
        assert "'unavailable'" not in lowered and "'no_data'" not in lowered, question


def test_join_specs_reference_known_tables(payload):
    identifiers = {table["identifier"] for table in payload["data_sources"]["tables"]}
    for join in payload["instructions"]["join_specs"]:
        assert join["left"]["identifier"] in identifiers
        assert join["right"]["identifier"] in identifiers
        assert join["sql"][-1].startswith("--rt=FROM_RELATIONSHIP_TYPE_")


def test_live_benchmark_suite_is_backed_by_benchmarks(payload):
    benchmarks = {item["question"][0] for item in payload["benchmarks"]["questions"]}
    suite = config.benchmark_suite()
    assert len(suite) >= 20
    assert len({case["id"] for case in suite}) == len(suite)
    for case in suite:
        assert case["question"] in benchmarks, case["question"]
        assert case["must_have_any"]


def test_lineage_view_is_bounded_by_event_date():
    statements = {item["name"]: item["sql"] for item in config.curated_view_statements(catalog=CATALOG, store_schema="axiom_alex")}
    assert "event_date >= date_sub(current_date(), 90)" in statements["axiom_ai_lineage_edges"]


def test_committed_agent_json_is_current(payload):
    assert COMMITTED.exists(), "run scripts/export_axiom_genie_agent.py"
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == payload
