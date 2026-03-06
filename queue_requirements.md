1. All natural language input and images will be added to a queue.
2. Chat interfaces must clearly separate in-built commands versus general input. in-built commands are NOT part of the queue as they will be executed immediately. general input refers to all natural language input and images.
3. There can only be ONE active conversation at a time. 
4. The first LLM response will always be one of the following:
  - a follow up question to gather more details
  - a statement with a yes / no answer
5. A conversation starts when the LLM successfully processes a message or image and has responded to the system initially, and there are no active conversations at the time.
6. A conversation is considered active until a memory has been saved or modified. This refers to the successful completion of:
  - saving an image with tags
  - setting a reminder 
  - creating a task
  - marking a task as done
  - completing a search query
  - deleting a memory
  - cancelling the current conversation using the cancel command
7. If multiple messages are sent while the LLM is processing a message, it gets added to the queue and will not process until the active conversation is completed.
8. The system must be sufficiently verbose to inform the user on the chat interface of what is happening.
9. During an active conversation, follow up text inputs will be processed along with the entire history of the conversation to maintain context. 
10. All relevant information must be provided. e.g current timestamp, timestamp of message, user timezone, etc.
11. All items in the queue persist up to a week.

# Example 1
1. User sends 2 messages in a row
2. The first message is clear, LLM responds with a reminder set with time.
3. User accepts and confirms
4. Memory saved, LLM now starts processing the second message.
5. The second message is clear, LLM responds with a task set with deadline.
6. User accepts and confirms
7. Memory saved

# Example 2
1. User sends 3 messages in a row
2. The first message is clear, LLM responds with a reminder set with time.
3. User accepts and confirms
4. Memory saved, LLM now starts processing the second message.
5. Second message is ambiguous, LLM follows up with a message.
6. User responds to the follow up, LLM processes this follow up message (skips the queue).
7. LLM responds with a task set with deadline.
8. User accepts and confirms.
9. Memory saved, LLM now starts processing the third message.

# Example 3
1. User sends 3 messages in a row
2. The first message is ambiguous, LLM follows up with a message.
3. User responds to the follow up, LLM processes this follow up message (skips the queue).
4. LLM responds with a reminder set with time.
5. User accepts and confirms.
6. Memory saved, LLM now starts processing the second message.
7. Second message is ambiguous, LLM follows up with a message.
8. User responds to the follow up, LLM processes this follow up message (skips the queue).
9. LLM responds with a task set with deadline.
10. User accepts and confirms.
11. Memory saved, LLM now starts processing the third message.