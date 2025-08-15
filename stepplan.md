- id: 1
  description: Enable image attachments in Chainlit UI (spontaneous uploads limited to images)
  status: DONE
  dependencies: []
- id: 2
  description: Add multimodal (text+image) handling in backend to send images to vision-capable LLM via LiteLLM
  status: DONE
  dependencies: [1]
  subtasks:
    - Parse image elements from incoming Chainlit messages
    - Convert images to data URLs (base64) or use provided URLs
    - Build OpenAI-style content parts (text + image_url)
- id: 3
  description: Update token truncation to handle multimodal message content safely
  status: DONE
  dependencies: [2]
- id: 4
  description: Run code quality checks (black, flake8, mypy) and tests; fix issues
  status: PENDING
  dependencies: [2, 3]
  subtasks:
    - Install dev tooling if missing
    - Execute format, lint, type-check, and tests
- id: 5
  description: Smoke test in UI by sending an image and verifying model response
  status: PENDING
  dependencies: [2, 3] 