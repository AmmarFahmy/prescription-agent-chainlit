## Task 1-3: Image attachment support and multimodal handling

- Summary: Enabled image uploads in Chainlit, added backend support to pass images to the GPT-5 vision-capable model via LiteLLM, and updated token truncation to work with multimodal content.
- Files modified:
  - `.chainlit/config.toml`: Enabled `features.spontaneous_file_upload` and restricted to `image/*`, reduced limits.
  - `app.py`: Added `_encode_image_to_data_url`, `_extract_image_parts_from_message`, `_build_user_message_content`; updated truncation logic to count tokens safely for multimodal content; integrated multimodal content in `on_message`.
  - `stepplan.md`: Added tasks and statuses.
- Reasoning/decisions:
  - Use Chainlit spontaneous upload to keep UI simple; limit to images and moderate size.
  - Use data URLs for local files to ensure the model receives the image reliably; fallback to element URL when provided.
  - Preserve existing tool flow and prompts; only augment user messages.
- Notes:
  - Ensure the selected model `openai/gpt-5-mini` supports vision input via LiteLLM. If not, switch to a vision-capable variant.
  - No external docs consulted. 