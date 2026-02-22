# Image input scenarios
Scenario 1
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends proposed tags
5. User confirms tags
6. Memory saved

Scenario 2
1. User sends an image
2. System is available and running fully
3. LLM processes the image and generates tags
4. System sends the proposed tags
5. User rejects the tags
6. System follows up with "key in tags" and "Delete entry"
7. User keys in tags manually
8. Memory saved

Scenario 3
1. User sends an image
2. System is available and not running fully, LLM system is not available.
3. Image is sent to the queue
4. System waits for the LLM system to be available
5. LLM system has recovered
6. LLM processes the image and generates tags
7. System sends proposed tags
8. User confirms tags
9. Memory saved

Scenario 4
1. User sends an image
2. System is available and not running fully, LLM system is not available.
3. Image is sent to the queue
4. System waits for the LLM system to be available
5. LLM system has recovered after 14 days
6. LLM processes the image and generates tags
7. System sends proposed tags
8. User confirms tags
9. Memory saved

Scenario 5
1. User sends an image
2. System is available and running fully
3. Image is sent to the queue
4. LLM processes the image and generates tags
5. System sends proposed tags
6. User did not respond within 7 days
7. Image discarded, no memory saved

# Text input scenarios
Task, Reminder, General text, Search

Scenario 6
1. User sends a text message "Remind me to do something in 5 mins"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger a reminder tool call
5. Reminder tool call shall be set to 5 minutes from message (input event) timestamp
6. System records this reminder and sets a time trigger
7. Time trigger sends a message to the user


Scenario 7
1. User sends a text message "I need to buy butter later at 6pm"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger a task tool call
5. 

Scenario 8
1. User sends a text message "Best method to get to mount fuji from hakone is ..."
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should generate tags for this generic text message
5. 

Scenario 9
1. User sends a text message "When did I last buy butter?"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it should trigger search with keywords extracted from text message
5. 

## Ambiguous text input
Scenario 10
1. User sends a text message "I need to buy butter later"
2. System is available and running fully
3. LLM processes the text message
4. LLM recognises that it needs more information, asks for clarity on `later`.
5. Systems sends question from LLM back to user
6. User answers the question
7. LLM proceess the text message
8. LLM recognises that it should trigger a task tool call
9. 


Scenario 11
1. User sends a text message "Remind me to do something after work"
2. System is available and not running fully, LLM system is down
3. LLM processes the text message
4. LLM recognises that it needs more information, asks for clarity on `after work`.
5. 