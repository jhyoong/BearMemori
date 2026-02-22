# Bug list

## Critical
1. Reminders not triggering

2. Natural language prompts not setting properly. E.g `remind me to leave house in 5 minutes` does not create a proper reminder with a trigger time.
  - Might have to revise requirements on memory capture for text input.
  - - If LLM is not available, text message should go into a queue AFTER a confirmation trigger.
  - - E.g User sends a text message. LLM endpoint is not responsive -> system checks up to 3 times in the background, then sends a follow up back to the user asking if they want to send this text to the queue.

## Minor