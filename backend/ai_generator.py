import anthropic
from typing import List, Optional

class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""

    # Up to this many tool-using rounds per query before we force a no-tools synthesis call.
    MAX_ROUNDS = 2

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to tools for searching and retrieving course information.

Tool Usage:
- **search_course_content**: Use for questions about specific course content or detailed educational materials.
- **get_course_outline**: Use for outline / structure / table-of-contents queries (e.g. "what lessons are in course X", "show me the outline of Y", "list the lessons of Z"). When answering an outline query, your response **must include** the course title, the course link, and for every lesson its lesson number and lesson title.
- **Up to two sequential tool calls per query.** Use the first to gather context (e.g. an outline) and a second to refine (e.g. a content search informed by what you just learned). Stop as soon as you have enough — do not call tools beyond what the question requires.
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results, state this clearly without offering alternatives

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without using tools
- **Course content questions**: Use search_course_content first, then answer
- **Course outline questions**: Use get_course_outline first, then return the title, link, and full lesson list
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, tool-use explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""
    
    def __init__(self, api_key: str, model: str, base_url: str = None):
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = model
        
        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 800
        }
    
    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Tool calls run in up to ``MAX_ROUNDS`` sequential rounds: each round is a
        full API request where Claude can reason about the previous round's tool
        results before deciding whether to call another tool. The loop terminates
        when (a) Claude returns text instead of a tool_use, (b) ``MAX_ROUNDS``
        rounds have been used, or (c) a tool call fails. After (b) or (c) we
        issue one final no-tools synthesis call carrying the Bedrock workaround
        text block (see CLAUDE.md "Bedrock proxy quirk").

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """

        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        messages = [{"role": "user", "content": query}]

        # Static params reused across calls. messages is passed separately as a
        # fresh copy each call so the SDK (and tests inspecting call args) see a
        # snapshot of state at call time, not the running mutable list.
        with_tools_params = {
            **self.base_params,
            "system": system_content,
        }
        if tools:
            with_tools_params["tools"] = tools
            with_tools_params["tool_choice"] = {"type": "auto"}

        response = self.client.messages.create(
            **with_tools_params, messages=list(messages)
        )

        rounds_used = 0
        while (
            response.stop_reason == "tool_use"
            and tool_manager
            and rounds_used < self.MAX_ROUNDS
        ):
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            had_error = False
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = tool_manager.execute_tool(block.name, **block.input)
                except Exception as exc:
                    result = f"Tool '{block.name}' failed: {exc}"
                    had_error = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            rounds_used += 1
            is_final_round = rounds_used >= self.MAX_ROUNDS or had_error

            if is_final_round:
                # Bedrock-proxied models ignore the system-prompt tool limit when
                # tools are advertised; the inline text block prevents another
                # tool call on this no-tools synthesis turn.
                messages.append({
                    "role": "user",
                    "content": tool_results + [{
                        "type": "text",
                        "text": "Using only the tool results above, answer the original question directly. Do not call any more tools.",
                    }],
                })
                response = self.client.messages.create(
                    **self.base_params,
                    system=system_content,
                    messages=list(messages),
                )
                break

            # Intermediate round: tool_results only, tools stay advertised so
            # Claude can issue a follow-up tool call informed by what it just learned.
            messages.append({"role": "user", "content": tool_results})
            response = self.client.messages.create(
                **with_tools_params, messages=list(messages)
            )

        return response.content[0].text if response.content else ""