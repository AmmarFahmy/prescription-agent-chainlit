from typing import List, Dict, Optional
import os
import chainlit as cl
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.google import Gemini
from agno.media import Image
from linkup import LinkupClient
from chainlit.input_widget import Select, Switch
from prompt import PRESCRIPTION_AGENT_PROMPT
from mistralai import Mistral
from mistralai.models import OCRResponse
from mistralai import DocumentURLChunk
from pathlib import Path


DEFAULT_OPENAI_MODEL = "o4-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_MISTRAL_MODEL = "mistral-ocr-latest"

linkup_client = LinkupClient(api_key=os.environ["LINKUP_API_KEY"])

# Initialize Mistral client for OCR
mistral_client = None
if os.getenv("MISTRAL_API_KEY"):
    mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

# Model options for the chat settings
MODEL_OPTIONS = {
    "OpenAI o4-mini (Reasoning)": {
        "provider": "openai",
        "model_id": "o4-mini",
        "reasoning": True
    },
    "Gemini 2.0 Flash": {
        "provider": "google",
        "model_id": "gemini-2.0-flash",
        "reasoning": False
    },
    # "Gemini 2.0 Flash (Experimental)": {
    #     "provider": "google",
    #     "model_id": "gemini-2.0-flash-exp",
    #     "reasoning": False
    # }
}


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


def _extract_agno_images_from_message(msg: cl.Message) -> List[Image]:
    """
    Extract Agno Image objects from message elements.
    """
    images = []
    for element in getattr(msg, "elements", []) or []:
        mime = getattr(element, "mime", None)
        if mime and isinstance(mime, str) and mime.startswith("image/"):
            path = getattr(element, "path", None)
            if path and isinstance(path, str) and os.path.exists(path):
                images.append(Image(filepath=path))
    return images


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


# Define the search tool for the agent
def search_web_tool(query: str, depth: str = "deep") -> str:
    """Search the web for real-time information."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(search_web(query, depth))
    finally:
        loop.close()


# Mistral OCR helper functions
def replace_images_in_markdown(markdown_str: str, images_dict: dict) -> str:
    """Replace image references in markdown with base64 data."""
    for img_name, base64_str in images_dict.items():
        markdown_str = markdown_str.replace(
            f"![{img_name}]({img_name})", f"![{img_name}]({base64_str})")
    return markdown_str


def get_combined_markdown(ocr_response: OCRResponse) -> str:
    """Combine OCR response pages into a single markdown string."""
    markdowns: list[str] = []
    for page in ocr_response.pages:
        image_data = {}
        for img in page.images:
            image_data[img.id] = img.image_base64
        markdowns.append(replace_images_in_markdown(page.markdown, image_data))

    return "\n\n".join(markdowns)


async def process_image_with_mistral_ocr(image_path: str) -> str:
    """Process image with Mistral OCR and return markdown."""
    if not mistral_client:
        raise ValueError(
            "Mistral client not initialized. Please set MISTRAL_API_KEY.")

    try:
        # Upload file to Mistral
        with open(image_path, 'rb') as f:
            file_content = f.read()

        uploaded_file = await cl.make_async(mistral_client.files.upload)(
            file={
                "file_name": Path(image_path).stem,
                "content": file_content,
            },
            purpose="ocr",
        )

        # Get signed URL
        signed_url = await cl.make_async(mistral_client.files.get_signed_url)(
            file_id=uploaded_file.id,
            expiry=1
        )

        # Process with OCR
        ocr_response = await cl.make_async(mistral_client.ocr.process)(
            document=DocumentURLChunk(document_url=signed_url.url),
            model=DEFAULT_MISTRAL_MODEL,
            include_image_base64=False
        )

        # Get combined markdown
        markdown_content = get_combined_markdown(ocr_response)
        return markdown_content

    except Exception as e:
        raise Exception(f"OCR processing failed: {str(e)}")


async def deep_understanding_workflow(agent, user_query: str, images: List[Image]) -> str:
    """
    Enhanced workflow with OCR extraction and verification.
    1. Extract text from images using Mistral OCR
    2. Verify extraction with o4-mini comparing image and markdown
    3. Generate comprehensive response using both image and verified markdown
    """
    # Process each image with OCR
    ocr_results = []

    for i, img in enumerate(images):
        try:
            # Show OCR processing message
            ocr_msg = cl.Message(
                content=f"🔍 Extracting text from image {i+1} using OCR...")
            await ocr_msg.send()

            # Process with Mistral OCR
            markdown_content = await process_image_with_mistral_ocr(img.filepath)
            ocr_results.append(markdown_content)

            # Update message
            ocr_msg.content = f"✅ Text extracted from image {i+1}"
            await ocr_msg.update()

        except Exception as e:
            error_msg = f"❌ OCR failed for image {i+1}: {str(e)}"
            await cl.Message(content=error_msg).send()
            ocr_results.append("")

    # Step 2: Verify extraction with o4-mini if it's available
    verification_msg = None
    verified_markdown = "\n\n".join(ocr_results)

    if "o4-mini" in agent.model.id:
        try:
            verification_msg = cl.Message(
                content="🔍 Verifying OCR extraction accuracy...")
            await verification_msg.send()

            # Create verification prompt
            verification_prompt = f"""You are an expert document analyzer. I have an image and its OCR-extracted text. 
Please carefully examine both and:
1. Verify if the OCR extraction captured all important information
2. Fix any missing or incorrect information
3. Return the corrected/verified markdown

OCR Extracted Text:
{verified_markdown}

Please provide the verified and corrected markdown text. Maintain the same structure but fix any errors or omissions."""

            # Create a non-reasoning agent for verification to avoid reasoning errors
            verification_agent = Agent(
                model=agent.model,
                description=agent.description,
                instructions=agent.instructions,
                tools=agent.tools,
                add_history_to_messages=False,
                markdown=True,
                reasoning=False  # Disable reasoning for verification
            )

            # Run verification with o4-mini
            verification_response = await cl.make_async(verification_agent.run)(
                verification_prompt,
                images=images,
                stream=False
            )

            # Extract verified content
            if hasattr(verification_response, 'content'):
                verified_markdown = verification_response.content
            elif hasattr(verification_response, 'get_content'):
                verified_markdown = verification_response.get_content()
            elif isinstance(verification_response, str):
                verified_markdown = verification_response
            else:
                verified_markdown = str(verification_response)

            verification_msg.content = "✅ OCR extraction verified and corrected"
            await verification_msg.update()

        except Exception as e:
            if verification_msg:
                verification_msg.content = f"⚠️ Verification skipped: {str(e)}"
                await verification_msg.update()

    # Step 3: Generate comprehensive response
    enhanced_prompt = f"""You have access to both the original image(s) and the extracted text content below.

Extracted Document Content:
{verified_markdown}

User Query: {user_query}

Please provide a comprehensive analysis based on BOTH the visual information from the image(s) AND the extracted text content. 
Ensure your response addresses the user's specific query while leveraging all available information."""

    return enhanced_prompt


def create_agent(model_name: str = "OpenAI o4-mini (Reasoning)"):
    """Create an agent based on the selected model."""
    model_config = MODEL_OPTIONS.get(
        model_name, MODEL_OPTIONS["OpenAI o4-mini (Reasoning)"])

    if model_config["provider"] == "openai":
        model = OpenAIChat(
            id=model_config["model_id"],
            api_key=os.getenv("OPENAI_API_KEY")
        )
    else:  # google
        model = Gemini(
            id=model_config["model_id"],
            api_key=os.getenv("GOOGLE_API_KEY")
        )

    # Add model signature to instructions
    model_signature = f"\n\nIMPORTANT: At the end of EVERY response, you MUST add a new line and then print exactly: 'Response generated by {model_config['model_id']}'"

    agent = Agent(
        model=model,
        description="You are an AI Senior Consultant Pharmacist with extensive clinical experience, serving as a mentor and guide to a team of pharmacists ranging from interns to senior practitioners. Your role is to analyze medical prescriptions, clinic bills, OPD invoices, and medical receipts with the highest level of accuracy and clinical insight.",
        # instructions=PRESCRIPTION_AGENT_PROMPT + model_signature,
        instructions=PRESCRIPTION_AGENT_PROMPT,
        tools=[search_web_tool],
        add_history_to_messages=True,
        markdown=True,
        reasoning=model_config.get("reasoning", False),
        reasoning_max_steps=10 if model_config.get(
            "reasoning", False) else None,
    )

    return agent


@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session and create the agent."""

    # Send chat settings
    settings = await cl.ChatSettings(
        [
            Select(
                id="Model",
                label="Model",
                values=list(MODEL_OPTIONS.keys()),
                initial_index=0,
            ),
            Switch(
                id="DeepUnderstanding",
                label="Deep Understanding (OCR + Verification)",
                initial=False,
                description="Enable advanced document analysis with OCR extraction and verification"
            ),
            Switch(
                id="Analyze",
                label="Analyze (Extract and review OCR)",
                initial=False,
                description="Extract the full markdown via OCR, review it, then proceed or redo"
            ),
        ]
    ).send()

    # Create default agent
    agent = create_agent()

    # Store agent in session
    cl.user_session.set("agent", agent)
    cl.user_session.set("chat_messages", [])
    cl.user_session.set("current_model", "OpenAI o4-mini (Reasoning)")
    cl.user_session.set("deep_understanding", False)
    cl.user_session.set("analyze_mode", False)
    cl.user_session.set("analyze_md", None)

    # Set available commands
    await cl.context.emitter.set_commands(COMMANDS)


@cl.on_settings_update
async def setup_agent(settings):
    """Handle settings update to switch between models or toggle modes."""
    selected_model = settings["Model"]
    current_model = cl.user_session.get("current_model")
    deep_understanding = settings.get("DeepUnderstanding", False)
    analyze_mode = settings.get("Analyze", False)
    current_deep_understanding = cl.user_session.get(
        "deep_understanding", False)
    current_analyze_mode = cl.user_session.get("analyze_mode", False)

    # Enforce mutual exclusivity
    if deep_understanding and analyze_mode:
        if analyze_mode != current_analyze_mode:
            deep_understanding = False
        elif deep_understanding != current_deep_understanding:
            analyze_mode = False

    # Persist toggles
    if deep_understanding != current_deep_understanding:
        cl.user_session.set("deep_understanding", deep_understanding)
        await cl.Message(content=f"🔍 Deep Understanding mode {'enabled' if deep_understanding else 'disabled'}").send()
    if analyze_mode != current_analyze_mode:
        cl.user_session.set("analyze_mode", analyze_mode)
        await cl.Message(content=f"🧪 Analyze mode {'enabled' if analyze_mode else 'disabled'}").send()
        if not analyze_mode:
            cl.user_session.set("analyze_md", None)

    # Check if model changed
    if selected_model != current_model:
        await cl.Message(content=f"Switching to {selected_model}...").send()
        agent = create_agent(selected_model)
        cl.user_session.set("agent", agent)
        cl.user_session.set("current_model", selected_model)
        await cl.Message(content=f"✅ Now using **{selected_model}**").send()


@cl.action_callback("proceed_next")
async def proceed_next(action: cl.Action):
    md = cl.user_session.get("analyze_md")
    if not md:
        await cl.Message(content="⚠️ No extracted content available. Please upload an image and enable Analyze.").send()
        return
    await cl.Message(content="➡️ Proceeding to chat with the extracted content.").send()
    # Prefill the user's query with extracted md for the next prompt
    cl.user_session.set("prefill_md", md)
    # Remove actions
    await cl.Action.remove("proceed_next")
    await cl.Action.remove("redo_ocr")


@cl.action_callback("redo_ocr")
async def redo_ocr(action: cl.Action):
    images = cl.user_session.get("last_images") or []
    if not images:
        await cl.Message(content="⚠️ No image found to reprocess. Please upload again.").send()
        return
    try:
        md = await process_image_with_mistral_ocr(images[0].filepath)
        cl.user_session.set("analyze_md", md)
        actions = [
            cl.Action(name="proceed_next", payload={
                      "value": "proceed"}, label="Proceed to Next", tooltip="Proceed to Next"),
            cl.Action(name="redo_ocr", payload={
                      "value": "redo"}, label="Redo", tooltip="Redo the OCR"),
        ]
        await cl.Message(content=md, actions=actions).send()
    except Exception as e:
        await cl.Message(content=f"❌ OCR extraction failed: {str(e)}").send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming messages and images from the user."""

    # Get session state
    agent = cl.user_session.get("agent")
    analyze_mode = cl.user_session.get("analyze_mode", False)

    # Extract images from uploaded files
    images = _extract_agno_images_from_message(message)
    cl.user_session.set("last_images", images)

    # Show uploaded images in chat
    for i, element in enumerate(message.elements or []):
        if "image" in getattr(element, "mime", ""):
            await cl.Message(
                content=f"✅ Received image: **{element.name}**",
                elements=[
                    cl.Image(
                        name=element.name,
                        path=element.path,
                        display="inline"
                    )
                ]
            ).send()

    # Analyze mode: run OCR, show markdown with actions, then stop until user clicks
    if analyze_mode and images:
        try:
            # Only process first image for now (extendable)
            md = await process_image_with_mistral_ocr(images[0].filepath)
            cl.user_session.set("analyze_md", md)

            # Show markdown with actions
            actions = [
                cl.Action(name="proceed_next", payload={
                          "value": "proceed"}, label="Proceed to Next", tooltip="Proceed to Next"),
                cl.Action(name="redo_ocr", payload={
                          "value": "redo"}, label="Redo", tooltip="Redo the OCR"),
            ]
            await cl.Message(content=md, actions=actions).send()
            return
        except Exception as e:
            await cl.Message(content=f"❌ OCR extraction failed: {str(e)}").send()
            return

    # Prepare the user's query
    prefill_md = cl.user_session.get("prefill_md")
    if prefill_md:
        user_query = f"Using the extracted OCR content below, address the user's questions and provide insights.\n\nExtracted Content (Markdown):\n{prefill_md}\n\nUser message: {message.content}"
        cl.user_session.set("prefill_md", None)
    else:
        user_query = message.content

    # If no specific question is asked with the image, provide a general analysis
    if images and not user_query.strip():
        user_query = PRESCRIPTION_AGENT_PROMPT

    # Handle explicit search command
    if message.command == "Search" and user_query:
        user_query = f"Please search the web for: {user_query}"

    # Check if Deep Understanding is enabled and we have images
    deep_understanding = cl.user_session.get("deep_understanding", False)
    if deep_understanding and images:
        user_query = await deep_understanding_workflow(agent, user_query, images)

    # Create a message for streaming the response
    response_msg = cl.Message(content="")
    await response_msg.send()

    # Show thinking indicator for reasoning models
    thinking_msg = None
    if agent.reasoning:
        current_model = cl.user_session.get("current_model", "Unknown Model")
        thinking_msg = cl.Message(content=f"{current_model} is thinking...")
        await thinking_msg.send()

    try:
        # Run the agent with streaming
        response_iterator = await cl.make_async(agent.run)(
            user_query,
            images=images,
            stream=True
        )

        # Track if we've started receiving actual content
        content_started = False

        # Stream the response chunks
        for chunk in response_iterator:
            content = None
            if chunk and hasattr(chunk, 'content'):
                content = chunk.content
            elif chunk and hasattr(chunk, 'get_content_as_string'):
                content = chunk.get_content_as_string()

            if content:
                if not content_started and thinking_msg:
                    await thinking_msg.remove()
                    thinking_msg = None
                    content_started = True

                await response_msg.stream_token(content)

        await response_msg.update()

    except Exception as stream_error:
        print(f"Streaming failed, using non-streaming mode: {stream_error}")

        try:
            if thinking_msg:
                await thinking_msg.remove()

            response = await cl.make_async(agent.run)(
                user_query,
                images=images,
                stream=False
            )

            if hasattr(response, 'content'):
                content = response.content
            elif hasattr(response, 'get_content'):
                content = response.get_content()
            else:
                content = str(response)

            await response_msg.stream_token(content)
            await response_msg.update()

        except Exception as e:
            if thinking_msg:
                await thinking_msg.remove()

            await cl.Message(content=f"❌ An error occurred: {str(e)}").send()
