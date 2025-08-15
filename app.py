from typing import Any, Dict, List, Optional
import json
import os
import base64
import chainlit as cl
import tokeniser
import litellm
from linkup import LinkupClient
from prompt import PROPOSAL_GENERATION_PROMPT


MAX_CONTEXT_WINDOW_TOKENS = 70000
DEFAULT_MODEL = "openai/gpt-5-mini"

linkup_client = LinkupClient(api_key=os.environ["LINKUP_API_KEY"])


# @cl.password_auth_callback
# def auth_callback(username: str, password: str):
#     # Fetch the user matching username from your database
#     # and compare the hashed password with the value stored in the database
#     if (username, password) == ("admin", "admin"):
#         return cl.User(
#             identifier="admin", metadata={"role": "admin", "provider": "credentials"}
#         )
#     else:
#         return None


def _encode_image_to_data_url(file_path: str, mime_type: str) -> Optional[str]:
    """
    Read an image file and return a data URL string suitable for OpenAI vision input.
    """
    try:
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        prefix = mime_type if mime_type else "image/png"
        return f"data:{prefix};base64,{b64}"
    except Exception:
        return None


def _extract_image_parts_from_message(msg: cl.Message) -> List[Dict[str, Any]]:
    """
    Build content parts for any image elements attached to the message.
    Returns a list of OpenAI-compatible content parts with type "image_url".
    """
    image_parts: List[Dict[str, Any]] = []
    try:
        for element in getattr(msg, "elements", []) or []:
            mime = getattr(element, "mime", None)
            if not (mime and isinstance(mime, str) and mime.startswith("image/")):
                continue

            # Prefer local path if available and readable
            path = getattr(element, "path", None)
            data_url: Optional[str] = None
            if path and isinstance(path, str) and os.path.exists(path):
                data_url = _encode_image_to_data_url(path, mime)
            else:
                # Fallback to remote URL if Chainlit provided one
                url = getattr(element, "url", None)
                if url and isinstance(url, str):
                    data_url = url

            if data_url:
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": data_url}
                })
    except Exception:
        # Fail open: if anything goes wrong, just skip images
        return []

    return image_parts


def _build_user_message_content(msg: cl.Message) -> Any:
    """
    Build the content field for a user message, combining text and any attached images.
    Returns either a string (text only) or a list of content parts for multimodal.
    """
    text = msg.content or ""
    image_parts = _extract_image_parts_from_message(msg)
    if image_parts:
        parts: List[Dict[str, Any]] = []
        if text:
            parts.append({"type": "text", "text": text})
        parts.extend(image_parts)
        return parts
    return text


@cl.oauth_callback
def oauth_callback(
        provider_id: str,
        token: str,  raw_user_data: Dict[str, str],
        default_user: cl.User,
) -> Optional[cl.User]:
    return default_user


@cl.on_chat_resume
async def on_chat_resume(thread):
    pass

# Tool definitions
SEARCH_TOOL = {
    "type": "function",
    "function": {
            "name": "search_web",
        "description": "Performs a search for user input query using Linkup sdk then returns a string of the top search results. Should be used to search real-time data.",
        "parameters": {
                    "type": "object",
                    "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query string"
                            },
                        "depth": {
                                "type": "string",
                                "description": "The depth of the search: 'standard' or 'deep'. Standard is faster, deep is more thorough."
                            }
                    },
            "required": ["query", "depth"]
        }
    }
}

# Available commands in the UI
COMMANDS = [
    {
        "id": "Search",
        "icon": "globe",
                "description": "Find on the web",
                "button": True,
                "persistent": True
    },
]


def truncate_messages(messages: List[Dict[str, Any]], max_tokens: int = MAX_CONTEXT_WINDOW_TOKENS) -> List[Dict[str, Any]]:
    """
    Truncate conversation messages to fit within token limit.
    Simply keeps the most recent messages that fit within the token budget.
    Ensures the last message is not from the assistant.

    Args:
            messages: List of conversation messages
            max_tokens: Maximum allowed tokens

    Returns:
            Truncated list of messages that fit within the token budget
    """
    if not messages:
        return []

    truncated = messages.copy()

    # Remove last message if it's from assistant
    if truncated and truncated[-1]["role"] == "assistant":
        truncated = truncated[:-1]

    total_tokens = 0

    def _count_tokens(content: Any) -> int:
        # Handle both string and multimodal content lists
        if isinstance(content, str):
            return tokeniser.estimate_tokens(content)
        if isinstance(content, list):
            text_content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            return tokeniser.estimate_tokens(text_content)
        # Fallback
        return 0

    # Work backwards from the end to keep most recent messages
    for i in range(len(truncated) - 1, -1, -1):
        message_tokens = _count_tokens(truncated[i]["content"])
        total_tokens += message_tokens

        if total_tokens > max_tokens:
            truncated = truncated[i + 1:]
            break

    # Double check: remove last message if it's from assistant after truncation
    if truncated and truncated[-1]["role"] == "assistant":
        truncated = truncated[:-1]

    return truncated


async def search_web(query: str, depth: str = "deep") -> str:
    """
    Search the web using Linkup SDK

    Args:
            query: The search query string
            depth: Search depth ("standard" or "deep")

    Returns:
            Formatted search results as markdown text
    """
    try:
        search_results = linkup_client.search(
            query=query,
            depth=depth,
            output_type="searchResults",
        )

        formatted_text = "Search results:\n\n"

        for i, result in enumerate(search_results.results, 1):
            formatted_text += f"{i}. **{result.name}**\n"
            formatted_text += f"   URL: {result.url}\n"
            formatted_text += f"   {result.content}\n\n"

        return formatted_text
    except Exception as e:
        return f"Search failed: {str(e)}"


async def process_tool_calls(tool_calls: Dict, context_messages: List[Dict[str, Any]], msg: cl.Message):
    """
    Process tool calls made by the model

    Args:
            tool_calls: Dictionary of tool calls from the model
            context_messages: Conversation context
            msg: Chainlit message object for streaming response

    Returns:
            The generated response after processing tool calls
    """
    # Show temporary "searching" message
    tmp_message = cl.Message(content="Searching the web...", author="Tool")
    await tmp_message.send()
    await cl.sleep(0.5)

    for _, tool_info in tool_calls.items():
        try:
            arguments = json.loads(tool_info["arguments"])

            if tool_info["name"] == "search_web":
                # Execute web search
                search_depth = arguments.get("depth", "deep")
                search_result = await search_web(
                    arguments["query"],
                    search_depth
                )

                # Add search results to conversation context
                context_messages.append({
                    "role": "user",
                    "content": search_result
                })

        except json.JSONDecodeError:
            await msg.stream_token("Error: Failed to parse tool arguments")
            return "Error: Failed to parse tool arguments"
        except Exception as e:
            await msg.stream_token(f"Error: Tool execution failed - {str(e)}")
            return f"Error: Tool execution failed - {str(e)}"

    # Remove temporary message
    await tmp_message.remove()

    # Generate final response with search results
    # system_prompt = "Based on the information, give a comprehensive answer. At the end of your answer, list the used sources with their name and url."
    system_prompt = PROPOSAL_GENERATION_PROMPT

    await msg.stream_token("\n\n")

    tool_response = ""
    stream = await litellm.acompletion(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt}, *context_messages],
        stream=True
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            tool_response += chunk.choices[0].delta.content
            await msg.stream_token(chunk.choices[0].delta.content)

    return tool_response


async def run_with_tools(messages: List[Dict[str, Any]], selected_tool: str = None) -> str:
    """
    Run a conversation through OpenAI with function calling enabled.

    Args:
            messages: List of conversation messages
            selected_tool: Optional tool to force using

    Returns:
            Generated response content
    """
    # Create message for streaming
    msg = cl.Message(content="", author="Agent")

    # Truncate messages to fit context window
    context_messages = truncate_messages(messages)

    # Configure tool choice
    tool_choice = "auto"
    if selected_tool:
        tool_choice = {"type": "function", "function": {"name": selected_tool}}

    # Initial response generation
    current_tool_calls = {}
    response_content = ""

    system_prompt = PROPOSAL_GENERATION_PROMPT

    # Stream the response
    try:
        stream = await litellm.acompletion(
            model=DEFAULT_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      *context_messages],
            tools=[SEARCH_TOOL],
            tool_choice=tool_choice,
            stream=True
        )

        async for chunk in stream:
            # Process text content
            if chunk.choices[0].delta.content:
                response_content += chunk.choices[0].delta.content
                await msg.stream_token(chunk.choices[0].delta.content)

            # Process tool calls
            if chunk.choices[0].delta.tool_calls:
                for tool_call in chunk.choices[0].delta.tool_calls:
                    tool_id = tool_call.index

                    # Initialize new tool call
                    if tool_id not in current_tool_calls and tool_call.function.name:
                        current_tool_calls[tool_id] = {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments or ""
                        }
                    # Append to existing tool call
                    elif tool_id in current_tool_calls:
                        current_tool_calls[tool_id]["arguments"] += tool_call.function.arguments or ""

            # Add assistant's response to context
            context_messages.append(
                {"role": "assistant", "content": response_content})

        # Send initial message
        await msg.send()

        # Process any tool calls and combine responses
        if current_tool_calls:
            if len(response_content) == 0:
                # Display initial message if no response content.
                # Can be the case when the user explicitly asks for a tool.
                # response_content = "To answer this question thoroughly, I'll need to use my tools !"
                response_content = ""
                await msg.stream_token(response_content)
                await msg.update()

            tool_response = await process_tool_calls(current_tool_calls, context_messages, msg)

            if tool_response:
                response_content = f"{response_content}\n\n{tool_response}"

        # Update the message with final content
        await msg.update()

        return response_content

    except Exception as e:
        error_msg = f"Error generating response: {str(e)}"
        await cl.Message(content=error_msg).send()
        return error_msg


@cl.on_chat_start
async def start_chat():
    """Initialize the chat session"""

    await cl.context.emitter.set_commands(COMMANDS)

    cl.user_session.set("chat_messages", [])


@cl.on_message
async def on_message(msg: cl.Message):
    """Handle incoming user messages"""

    chat_messages = cl.user_session.get("chat_messages", [])

    # Build user content (text + images if any)
    user_content = _build_user_message_content(msg)
    chat_messages.append({"role": "user", "content": user_content})

    # Process message with or without explicit search command
    if msg.command == "Search":
        response = await run_with_tools(chat_messages, "search_web")
    else:
        response = await run_with_tools(chat_messages)

    chat_messages.append({"role": "assistant", "content": response})
    cl.user_session.set("chat_messages", chat_messages)
