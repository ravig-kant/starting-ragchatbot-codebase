from typing import Any, Dict, List, Optional, Tuple

import anthropic


class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to two tools for course information.

Available Tools:
- **get_course_outline**: Returns a course's title, course link, and complete lesson list (lesson number and title)
- **search_course_content**: Searches course materials for specific content or detailed educational information

Tool Usage:
- **Outline / structure questions** (course outline, lesson list, what lessons a course has, how many lessons): use get_course_outline
 - The answer must include the course title, the course link, and the number and title of every lesson
- **Specific course content questions**: use search_course_content
- **Up to 2 sequential tool calls per query**: you see each tool's results before deciding on the next call
 - Example: use get_course_outline to find the title of a course's lesson, then search_course_content for that topic
 - Example: comparisons or multi-part questions that need information from different courses or lessons
 - Make a second call only when the first result is insufficient; never repeat an identical call
 - As soon as you have enough information, answer without further tool calls
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results, state this clearly without offering alternatives
- If a tool reports an error, answer with what you have and briefly state what couldn't be retrieved

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without using tools
- **Course-specific questions**: Use the appropriate tool(s) first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    def __init__(self, api_key: str, model: str, max_tool_rounds: int = 2):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tool_rounds = max(0, max_tool_rounds)

        # Pre-build base API parameters
        self.base_params = {"model": self.model, "temperature": 0, "max_tokens": 800}

    def generate_response(
        self,
        query: str,
        conversation_history: Optional[str] = None,
        tools: Optional[List] = None,
        tool_manager=None,
    ) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """

        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        messages = [{"role": "user", "content": query}]

        # Each round is a separate API call in which Claude sees all earlier tool results
        for _ in range(self.max_tool_rounds):
            response = self._call_api(messages, system_content, tools)

            # No tool use requested (or nothing to run tools with) - this is the answer
            if response.stop_reason != "tool_use" or tool_manager is None:
                return self._extract_text(response)

            tool_results, had_error = self._execute_tools(response, tool_manager)
            if not tool_results:
                return self._extract_text(response)

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            # A failed tool ends tool use; Claude explains in the final answer
            if had_error:
                break

        # Rounds exhausted or a tool failed: final call without tools forces a text answer
        final_response = self._call_api(messages, system_content, tools=None)
        return self._extract_text(final_response)

    def _call_api(
        self, messages: List[Dict[str, Any]], system: str, tools: Optional[List] = None
    ):
        """Make one API call; messages are copied so each request keeps its own snapshot"""
        api_params = {**self.base_params, "messages": list(messages), "system": system}
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}
        return self.client.messages.create(**api_params)

    @staticmethod
    def _execute_tools(response, tool_manager) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Execute every tool_use block in a response.

        Returns:
            (tool_result blocks, whether any tool raised). Never raises; every
            tool_use block gets a result because the API requires one per call.
        """
        tool_results = []
        had_error = False
        for content_block in response.content:
            if getattr(content_block, "type", None) != "tool_use":
                continue
            result_block = {"type": "tool_result", "tool_use_id": content_block.id}
            try:
                result_block["content"] = tool_manager.execute_tool(
                    content_block.name, **content_block.input
                )
            except Exception as e:
                # Report the failure to Claude instead of failing the whole request
                result_block["content"] = f"Tool error: {e}"
                result_block["is_error"] = True
                had_error = True
            tool_results.append(result_block)
        return tool_results, had_error

    @staticmethod
    def _extract_text(response) -> str:
        """Join all text blocks of a response; never index into an empty or non-text content list"""
        texts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        text = "\n".join(t for t in texts if t).strip()
        return (
            text
            or "I wasn't able to generate a response. Please try rephrasing your question."
        )
