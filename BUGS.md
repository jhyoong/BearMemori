# Bug list

## Critical
1. Timeout from LLM doesn't seem to retry properly

2. Natural language prompts not working properly. E.g `remind me to leave house in 5 minutes` does not create a proper reminder with a trigger time.
  - Detects as reminder, but doesn't automatically register the time to set even though it is clear

3. Search query not working properly. When asked `Search for all images about anime`, the search triggered for the specific `No results found for "all images about anime".` which isn't natural.

4. Reminders are being saved as tasks. No clear definition between the two? Reminders only need to be fired off by the system on the time set. Reminders shouldn't have the 'mark as done' flow. 

## Minor
Old Telegram menu still showing up - need to replace with current ones