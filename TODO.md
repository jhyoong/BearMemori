# Bug list

## Critical
1. assistant chatbot - unable to actually make tasks or reminders. Telegram interface in this assistance will need a yes / no option for allowing creation of tasks/reminders/memories.

2. Conversation flow in ambiguous intent needs to be fixed. The behaviour should be adjusted to: 1. send follow up message. 2. Confirm with the user in natural language, asking if it is correct or not ( telegram yes / no buttons ) 3. Send the actual tool call with the correct information if user presses yes, or send another follow up message to user if pressed no. Continues for up to 3 nos before cancelling the current conversation ( ask the user to retry ). The entire conversation history must be maintained in this period and sent to the LLM so that it has all of the context needed, such as timestamps and current user timezone. 

## Minor
1. Editing tags on pictures seem to add them. This needs to be better managed ( edit vs add vs delete tags )

# Feature / Updates
## Important
1. Need better visualisation of current queue. Since this system relies on local models which are not stable, there needs to be a more robust handling mechanism in the system to deal with periods of unavailability or failures. 

~~2. Timezone setting, all timestamps to include timezone, even when sending back responses to user.~~ (Implemented in v0.1.1)

~~3. When setting reminders or tasks, if regex check fails for proper timestamp format, fallback to LLM processing to generate a timestamp from the user's response.~~ (Implemented in v0.1.1)

## Minor
1. Better visualisation of assistant worldview of user.
2. Code cleanup
   - Magic numbers, define constants centrally
   - simplifying complex areas
3. Web search functionality in assistant module.

---

## v0.1.1 Release Notes

The following TODO items have been resolved in v0.1.1:

- **Timezone support**: All timestamps now include timezone information in responses to users
- **LLM fallback for reminders**: When regex fails to parse timestamps in natural language, the system now falls back to LLM processing to generate proper timestamps
- **Memory interaction bug**: Fixed issue where telegram buttons didn't respond for images without descriptions (only delete worked)
- **Reminder time override bug**: Fixed issue where the system would override the LLM-proposed time and ask for manual input
