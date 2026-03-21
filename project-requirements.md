BearMemori will be a memory store project. It does not need to be designed for scale, and will be used as a personal memory store only.

# Requirements
1. The main interface that the user will interact with this is via a chat interface like Telegram or Whatsapp.
2. The main core structure should be designed so that it can be easily adapted to a different user interface if required.
3. The main inputs to this system from the user will be:
    - text
    - images
    - voice
    - logs
4. All inputs will be added to a queue with a priority system. This queue will need to hold items for up to 2 weeks. There is no need for the queue to persist between system restarts.
5. All inputs will be processed by a LLM. The LLM will decide how the input will be stored into the memory store.
6. Only one active input will be processed at a time. No parallel processing, assume that the LLM endpoint will be a bottleneck. 
7. A follow up system will be required to gather more clarity of the user's input if required. 
    - The system will need to be able to set follow up inputs as high priority in the queue so that it will be processed next.
    - Context of the entire conversation will need to be maintained for followups.
    - Followups will continue until the LLM has enough information to make a decision on how to store the memory.
8. Users should have the ability to search, edit, delete memories stored. 
9. Memories must contain all key information
    - timestamp
    - content
    - tags
    - type
10. This memory store will be mainly used by LLMs to gather key information about the user. Items such as user preferences, important timed events, etc should be easily searched and made available to the LLM calling this memory store.