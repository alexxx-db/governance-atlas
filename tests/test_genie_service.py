from __future__ import annotations

import unittest
from types import SimpleNamespace

from axiom.config import AppConfig
from axiom.services import genie


class FakeGenieClient:
    def __init__(self, message, statement=None, started=None):
        self.genie = SimpleNamespace(
            start_conversation_and_wait=self.start_conversation_and_wait,
            start_conversation=self.start_conversation,
            get_message=self.get_message,
        )
        self.statement_execution = (
            SimpleNamespace(get_statement=lambda statement_id: statement)
            if statement is not None
            else None
        )
        self.message = message
        self.started = started
        self.calls = []
        self.get_message_calls = []

    def start_conversation_and_wait(self, **kwargs):
        self.calls.append(kwargs)
        return self.message

    def start_conversation(self, **kwargs):
        self.calls.append(kwargs)
        return self.started

    def get_message(self, **kwargs):
        self.get_message_calls.append(kwargs)
        return self.message


class GenieServiceTests(unittest.TestCase):
    def _config(self, **overrides):
        data = {
            "warehouse_id": "warehouse-123",
            "gov_catalog": "emet",
            "gov_schema": "axiom",
            "genie_space_id": "",
            "genie_space_title": "Axiom Metadata Room",
            "axiom_ai_provider": "local",
        }
        data.update(overrides)
        return AppConfig(**data)

    def test_provider_status_without_genie_is_unavailable_not_local_evidence(self) -> None:
        status = genie.provider_status(self._config(axiom_ai_provider="local"))

        self.assertEqual(status["provider"], "unavailable")
        self.assertEqual(status["state"], "unavailable")
        self.assertIn("configured Databricks Genie space", status["message"])

    def test_provider_status_requires_space_id_for_genie(self) -> None:
        status = genie.provider_status(self._config(axiom_ai_provider="genie"))

        self.assertEqual(status["provider"], "genie")
        self.assertEqual(status["state"], "unavailable")
        self.assertIn("AXIOM_GENIE_SPACE_ID", status["message"])

    def test_ask_genie_normalizes_text_and_query_evidence(self) -> None:
        message = SimpleNamespace(
            status="COMPLETED",
            conversation_id="conv-1",
            message_id="msg-1",
            attachments=[
                SimpleNamespace(
                    attachment_id="att-1",
                    text=SimpleNamespace(content="Customer has the highest open work count."),
                    query=SimpleNamespace(
                        query="SELECT domain, count(*) FROM axiom_ai_assets_current GROUP BY domain",
                        title="Domain open work",
                        statement_id="stmt-1",
                        query_result_metadata={"row_count": 3, "is_truncated": False},
                    ),
                )
            ],
        )
        client = FakeGenieClient(message)

        payload = genie.ask_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            question="Which domains need stewardship?",
            client=client,
        )

        self.assertEqual(client.calls[0]["space_id"], "space-1")
        self.assertEqual(payload["provider"], "genie")
        self.assertEqual(payload["answer"], "Customer has the highest open work count.")
        self.assertEqual(payload["confidence"], "genie-grounded")
        self.assertEqual(payload["evidence"][0]["statementId"], "stmt-1")
        self.assertEqual(payload["evidence"][0]["rowCount"], 3)
        self.assertEqual(payload["conversationId"], "conv-1")

    def test_ask_genie_suppresses_negative_answer_when_query_has_rows(self) -> None:
        message = SimpleNamespace(
            status="COMPLETED",
            conversation_id="conv-2",
            message_id="msg-2",
            attachments=[
                SimpleNamespace(
                    attachment_id="att-2",
                    query=SimpleNamespace(
                        query="SELECT asset_fqn FROM axiom_ai_assets_current WHERE is_critical = TRUE",
                        statement_id="stmt-2",
                        query_result_metadata={"row_count": 2},
                    ),
                ),
                SimpleNamespace(
                    text=SimpleNamespace(content="There are no critical assets that are not certified."),
                ),
            ],
        )
        statement = SimpleNamespace(
            manifest=SimpleNamespace(
                total_row_count=2,
                schema=SimpleNamespace(
                    columns=[
                        SimpleNamespace(name="asset_fqn"),
                        SimpleNamespace(name="domain"),
                    ]
                ),
            ),
            result=SimpleNamespace(
                data_array=[
                    ["main.customer.orders", "Customer"],
                    ["main.finance.payments", "Finance"],
                ]
            ),
        )
        client = FakeGenieClient(message, statement=statement)

        payload = genie.ask_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            question="Which critical assets are not certified?",
            client=client,
        )

        self.assertIn("Genie returned 2 governed evidence rows", payload["answer"])
        self.assertIn("main.customer.orders", payload["answer"])
        self.assertIn("text conflicted", payload["warnings"][0].lower())
        self.assertEqual(payload["evidence"][0]["totalRowCount"], 2)

    def test_ask_genie_strips_sentinel_no_result_rows(self) -> None:
        message = SimpleNamespace(
            status="COMPLETED",
            conversation_id="conv-3",
            message_id="msg-3",
            attachments=[
                SimpleNamespace(
                    attachment_id="att-3",
                    text=SimpleNamespace(content="No data quality issues found for critical assets."),
                    query=SimpleNamespace(
                        query=(
                            "SELECT quality.asset_fqn, quality.column_name, quality.detail "
                            "FROM axiom_ai_quality_latest quality "
                            "UNION ALL SELECT 'unavailable', NULL, "
                            "'No data quality issues found for critical assets.'"
                        ),
                        statement_id="stmt-3",
                        query_result_metadata={"row_count": 1},
                    ),
                )
            ],
        )
        statement = SimpleNamespace(
            manifest=SimpleNamespace(
                total_row_count=1,
                schema=SimpleNamespace(
                    columns=[
                        SimpleNamespace(name="asset_fqn"),
                        SimpleNamespace(name="column_name"),
                        SimpleNamespace(name="detail"),
                    ]
                ),
            ),
            result=SimpleNamespace(
                data_array=[
                    ["unavailable", None, "No data quality issues found for critical assets."],
                ]
            ),
        )
        client = FakeGenieClient(message, statement=statement)

        payload = genie.ask_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            question="Show me data quality issues impacting critical assets.",
            client=client,
        )

        self.assertEqual(payload["evidence"][0]["rowCount"], 0)
        self.assertEqual(payload["evidence"][0]["totalRowCount"], 0)
        self.assertNotIn("resultRows", payload["evidence"][0])
        self.assertNotIn("1 governed evidence row", payload["answer"])
        self.assertTrue(any("sentinel no-result" in warning.lower() for warning in payload["warnings"]))

    def test_genie_stage_labels_map_message_status(self) -> None:
        self.assertEqual(genie.genie_stage_label("FILTERING_CONTEXT"), "Selecting relevant tables")
        self.assertEqual(genie.genie_stage_label("ASKING_AI"), "Generating the SQL query")
        self.assertEqual(genie.genie_stage_label("EXECUTING_QUERY"), "Running the query")
        self.assertEqual(genie.genie_stage_label("unknown-thing"), "Working")

    def test_start_genie_returns_ids_and_stage_without_waiting(self) -> None:
        started = SimpleNamespace(conversation_id="conv-9", message_id="msg-9", status="SUBMITTED")
        client = FakeGenieClient(message=None, started=started)

        result = genie.start_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            question="Which domains need stewardship?",
            client=client,
        )

        self.assertEqual(client.calls[0]["space_id"], "space-1")
        self.assertEqual(result["conversationId"], "conv-9")
        self.assertEqual(result["messageId"], "msg-9")
        self.assertEqual(result["stage"], "Submitted to Genie")

    def test_poll_genie_executing_query_is_not_done(self) -> None:
        # Review B1: EXECUTING_QUERY means the SQL is still running — polling
        # must NOT finalize here (the answer + rows aren't ready), it keeps going.
        message = SimpleNamespace(status="EXECUTING_QUERY", conversation_id="conv-9", message_id="msg-9")
        client = FakeGenieClient(message)

        result = genie.poll_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            conversation_id="conv-9", message_id="msg-9", client=client,
        )

        self.assertEqual(client.get_message_calls[0]["conversation_id"], "conv-9")
        self.assertFalse(result["done"])
        self.assertEqual(result["stage"], "Running the query")
        self.assertNotIn("payload", result)

    def test_poll_genie_completed_finalizes_with_payload(self) -> None:
        message = SimpleNamespace(
            status="COMPLETED", conversation_id="conv-9", message_id="msg-9",
            attachments=[SimpleNamespace(text=SimpleNamespace(content="Two assets are uncertified."))],
        )
        client = FakeGenieClient(message)

        result = genie.poll_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            conversation_id="conv-9", message_id="msg-9", client=client,
        )

        self.assertTrue(result["done"])
        self.assertEqual(result["stage"], "Done")
        self.assertEqual(result["payload"]["answer"], "Two assets are uncertified.")

    def test_start_genie_reads_sdk_wait_without_keyerror(self) -> None:
        # The real SDK returns a Wait whose __getattr__ raises KeyError for keys
        # outside its bind dict; ids live on `.response`. start_genie must not
        # blow up on that shape.
        class KeyErrorWait:
            def __init__(self):
                self.response = SimpleNamespace(
                    conversation_id="conv-w", message_id="msg-w",
                    message=SimpleNamespace(status="FETCHING_METADATA"),
                )

            def __getattr__(self, key):  # mimic databricks Wait.__getattr__
                raise KeyError(key)

        client = FakeGenieClient(message=None, started=KeyErrorWait())
        result = genie.start_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            question="Which assets need stewardship?", client=client,
        )
        self.assertEqual(result["conversationId"], "conv-w")
        self.assertEqual(result["messageId"], "msg-w")
        self.assertEqual(result["stage"], "Reading governed metadata")

    def test_poll_genie_pending_has_no_payload(self) -> None:
        message = SimpleNamespace(status="FILTERING_CONTEXT", conversation_id="c", message_id="m")
        client = FakeGenieClient(message)

        result = genie.poll_genie(
            config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
            conversation_id="c", message_id="m", client=client,
        )

        self.assertFalse(result["done"])
        self.assertEqual(result["stage"], "Selecting relevant tables")
        self.assertNotIn("payload", result)

    def test_poll_genie_raises_on_failed_status(self) -> None:
        message = SimpleNamespace(status="FAILED", conversation_id="c", message_id="m")
        client = FakeGenieClient(message)

        with self.assertRaises(RuntimeError):
            genie.poll_genie(
                config=self._config(axiom_ai_provider="genie", genie_space_id="space-1"),
                conversation_id="c", message_id="m", client=client,
            )


if __name__ == "__main__":
    unittest.main()
