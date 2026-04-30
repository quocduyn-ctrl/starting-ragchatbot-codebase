"""Unit tests for AIGenerator's tool-calling flow.

Strategy: mock the Anthropic client so we can verify the wire-level contract —
what params each round sends, when tools are/aren't included, how messages
compose across multiple rounds, and that the Bedrock workaround text block is
preserved on the final no-tools synthesis call.
"""
import unittest
from unittest.mock import MagicMock, patch

from ai_generator import AIGenerator


def _text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_use_block(name, inp, id_="tu_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = inp
    block.id = id_
    return block


def _make_generator(fake_client):
    with patch("ai_generator.anthropic.Anthropic", return_value=fake_client):
        return AIGenerator(api_key="k", model="m", base_url="https://x")


class TestAIGeneratorFirstCall(unittest.TestCase):

    def test_passes_tools_and_tool_choice_when_tools_provided(self):
        client = MagicMock()
        rsp = MagicMock()
        rsp.stop_reason = "end_turn"
        rsp.content = [_text_block("hello")]
        client.messages.create.return_value = rsp

        gen = _make_generator(client)
        tools = [{"name": "search_course_content", "description": "d",
                  "input_schema": {"type": "object", "properties": {}}}]
        gen.generate_response(query="q", tools=tools, tool_manager=MagicMock())

        kwargs = client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["tools"], tools)
        self.assertEqual(kwargs["tool_choice"], {"type": "auto"})
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "q"}])
        self.assertIn("course materials", kwargs["system"].lower())

    def test_omits_tools_when_none_provided(self):
        client = MagicMock()
        rsp = MagicMock()
        rsp.stop_reason = "end_turn"
        rsp.content = [_text_block("plain")]
        client.messages.create.return_value = rsp

        gen = _make_generator(client)
        gen.generate_response(query="q")

        kwargs = client.messages.create.call_args.kwargs
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)

    def test_returns_text_directly_when_no_tool_use(self):
        client = MagicMock()
        rsp = MagicMock()
        rsp.stop_reason = "end_turn"
        rsp.content = [_text_block("plain answer")]
        client.messages.create.return_value = rsp

        gen = _make_generator(client)
        out = gen.generate_response(query="q")

        self.assertEqual(out, "plain answer")
        self.assertEqual(client.messages.create.call_count, 1)


class TestAIGeneratorToolFlow(unittest.TestCase):

    def test_tool_use_response_invokes_tool_manager_with_correct_args(self):
        client = MagicMock()
        first = MagicMock()
        first.stop_reason = "tool_use"
        first.content = [_tool_use_block(
            "search_course_content",
            {"query": "what is rag", "course_name": "MCP", "lesson_number": 5},
            "tu_a",
        )]
        second = MagicMock()
        second.stop_reason = "end_turn"
        second.content = [_text_block("synthesized answer")]
        client.messages.create.side_effect = [first, second]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "[MCP - Lesson 5]\nbody"

        result = gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        manager.execute_tool.assert_called_once_with(
            "search_course_content",
            query="what is rag",
            course_name="MCP",
            lesson_number=5,
        )
        self.assertEqual(result, "synthesized answer")
        self.assertEqual(client.messages.create.call_count, 2)

    def test_round_2_includes_round_1_tool_result_block(self):
        client = MagicMock()
        first = MagicMock()
        first.stop_reason = "tool_use"
        first.content = [_tool_use_block(
            "search_course_content", {"query": "x"}, id_="tu_42"
        )]
        second = MagicMock()
        second.stop_reason = "end_turn"
        second.content = [_text_block("done")]
        client.messages.create.side_effect = [first, second]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "the actual results"

        gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        second_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        last = second_messages[-1]
        tool_results = [
            c for c in last["content"]
            if isinstance(c, dict) and c.get("type") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["tool_use_id"], "tu_42")
        self.assertEqual(tool_results[0]["content"], "the actual results")

    def test_two_sequential_rounds_uses_first_result_to_inform_second(self):
        """Headline test for the new feature. Round 1 fetches an outline, round 2
        uses information from that outline to drive a content search, and the
        third call returns the final answer (matches the example flow in the
        prompt: 'search for a course that discusses the same topic as lesson 4
        of course X')."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block(
            "get_course_outline", {"course_name": "X"}, id_="tu_outline"
        )]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block(
            "search_course_content", {"query": "lesson 4 title topic"}, id_="tu_search"
        )]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("Course Y")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.side_effect = [
            "Lesson 4 — Some Topic",
            "Course Y matches",
        ]

        result = gen.generate_response(
            query="Search for a course that discusses the same topic as lesson 4 of course X",
            tools=[
                {"name": "get_course_outline"},
                {"name": "search_course_content"},
            ],
            tool_manager=manager,
        )

        self.assertEqual(client.messages.create.call_count, 3)
        self.assertEqual(manager.execute_tool.call_count, 2)
        first_call = manager.execute_tool.call_args_list[0]
        self.assertEqual(first_call.args[0], "get_course_outline")
        self.assertEqual(first_call.kwargs, {"course_name": "X"})
        second_call = manager.execute_tool.call_args_list[1]
        self.assertEqual(second_call.args[0], "search_course_content")
        self.assertEqual(second_call.kwargs, {"query": "lesson 4 title topic"})
        self.assertEqual(result, "Course Y")

    def test_intermediate_round_keeps_tools_and_omits_workaround_text(self):
        """The round-2 call (after round-1 tool use, before any cap is hit) must
        still advertise tools — otherwise Claude can't make a second tool call —
        and must NOT carry the Bedrock workaround text, which would defeat the
        feature."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("get_course_outline", {"course_name": "X"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block("search_course_content", {"query": "y"}, "tu_b")]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("done")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        tools = [
            {"name": "get_course_outline"},
            {"name": "search_course_content"},
        ]
        gen.generate_response(query="q", tools=tools, tool_manager=manager)

        second_kwargs = client.messages.create.call_args_list[1].kwargs
        self.assertEqual(second_kwargs["tools"], tools)
        self.assertEqual(second_kwargs["tool_choice"], {"type": "auto"})

        last_user_msg = second_kwargs["messages"][-1]
        self.assertEqual(last_user_msg["role"], "user")
        text_blocks = [
            c for c in last_user_msg["content"]
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        self.assertEqual(text_blocks, [],
                         "intermediate round must NOT carry the workaround text block")

    def test_round_cap_enforced_after_two_tool_rounds(self):
        """After two tool-using rounds, the loop terminates and issues exactly
        one final no-tools synthesis call, even if Claude wanted to call tools
        again."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("search_course_content", {"query": "a"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block("search_course_content", {"query": "b"}, "tu_b")]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("final")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        result = gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        self.assertEqual(client.messages.create.call_count, 3)
        third_kwargs = client.messages.create.call_args_list[2].kwargs
        self.assertNotIn("tools", third_kwargs)
        self.assertNotIn("tool_choice", third_kwargs)
        self.assertEqual(result, "final")

    def test_final_synthesis_call_omits_tools(self):
        """Per CLAUDE.md, the final no-tools synthesis call must not advertise
        tools, otherwise Bedrock-proxied models will keep calling them in a loop."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("search_course_content", {"query": "x"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block("search_course_content", {"query": "y"}, "tu_b")]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("done")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        third_kwargs = client.messages.create.call_args_list[2].kwargs
        self.assertNotIn("tools", third_kwargs)
        self.assertNotIn("tool_choice", third_kwargs)

    def test_final_synthesis_call_appends_workaround_text_block(self):
        """The inline text block on the final no-tools call prevents Bedrock
        from attempting another tool call (per CLAUDE.md). Lock the contract in."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("search_course_content", {"query": "x"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block("search_course_content", {"query": "y"}, "tu_b")]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("done")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        third_messages = client.messages.create.call_args_list[2].kwargs["messages"]
        last = third_messages[-1]
        self.assertEqual(last["role"], "user")
        text_blocks = [
            c for c in last["content"]
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        self.assertTrue(text_blocks, "expected a text block instructing not to call tools")
        joined = " ".join(b["text"] for b in text_blocks)
        self.assertIn("Do not call any more tools", joined)

    def test_tool_error_terminates_after_one_round(self):
        """If a tool raises, the round closes with the error formatted as the
        tool_result content, and the next call is the no-tools synthesis call —
        not a second tool round. Prevents flaky tools from being retried twice
        and lets Claude phrase the failure naturally."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("search_course_content", {"query": "x"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "end_turn"
        r2.content = [_text_block("sorry, search failed")]
        client.messages.create.side_effect = [r1, r2]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.side_effect = RuntimeError("boom")

        result = gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )

        self.assertEqual(client.messages.create.call_count, 2)
        second_kwargs = client.messages.create.call_args_list[1].kwargs
        self.assertNotIn("tools", second_kwargs)
        last_user_msg = second_kwargs["messages"][-1]
        tool_results = [
            c for c in last_user_msg["content"]
            if isinstance(c, dict) and c.get("type") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("failed", tool_results[0]["content"])
        self.assertIn("boom", tool_results[0]["content"])
        self.assertEqual(result, "sorry, search failed")

    def test_tool_use_id_propagates_each_round(self):
        """tool_result blocks across rounds must carry the matching tool_use_id."""
        client = MagicMock()
        r1 = MagicMock()
        r1.stop_reason = "tool_use"
        r1.content = [_tool_use_block("get_course_outline", {"course_name": "X"}, "tu_a")]
        r2 = MagicMock()
        r2.stop_reason = "tool_use"
        r2.content = [_tool_use_block("search_course_content", {"query": "y"}, "tu_b")]
        r3 = MagicMock()
        r3.stop_reason = "end_turn"
        r3.content = [_text_block("done")]
        client.messages.create.side_effect = [r1, r2, r3]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        gen.generate_response(
            query="q",
            tools=[{"name": "get_course_outline"}, {"name": "search_course_content"}],
            tool_manager=manager,
        )

        round_2_user = client.messages.create.call_args_list[1].kwargs["messages"][-1]
        round_2_results = [
            c for c in round_2_user["content"]
            if isinstance(c, dict) and c.get("type") == "tool_result"
        ]
        self.assertEqual(round_2_results[0]["tool_use_id"], "tu_a")

        round_3_user = client.messages.create.call_args_list[2].kwargs["messages"][-1]
        round_3_results = [
            c for c in round_3_user["content"]
            if isinstance(c, dict) and c.get("type") == "tool_result"
        ]
        self.assertEqual(round_3_results[0]["tool_use_id"], "tu_b")

    def test_handles_empty_final_content_gracefully(self):
        """Bedrock occasionally returns content=[] under load; must not crash."""
        client = MagicMock()
        first = MagicMock()
        first.stop_reason = "tool_use"
        first.content = [_tool_use_block("search_course_content", {"query": "x"})]
        empty = MagicMock()
        empty.stop_reason = "end_turn"
        empty.content = []
        client.messages.create.side_effect = [first, empty]

        gen = _make_generator(client)
        manager = MagicMock()
        manager.execute_tool.return_value = "results"

        out = gen.generate_response(
            query="q",
            tools=[{"name": "search_course_content"}],
            tool_manager=manager,
        )
        self.assertEqual(out, "")


class TestAIGeneratorInit(unittest.TestCase):

    def test_passes_base_url_to_anthropic_client_when_provided(self):
        with patch("ai_generator.anthropic.Anthropic") as mock_cls:
            AIGenerator(api_key="k", model="m", base_url="https://nv")
        kwargs = mock_cls.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "k")
        self.assertEqual(kwargs["base_url"], "https://nv")

    def test_omits_base_url_when_not_provided(self):
        with patch("ai_generator.anthropic.Anthropic") as mock_cls:
            AIGenerator(api_key="k", model="m")
        kwargs = mock_cls.call_args.kwargs
        self.assertNotIn("base_url", kwargs)


if __name__ == "__main__":
    unittest.main()
