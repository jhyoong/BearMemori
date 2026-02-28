# Bug list

## Critical
1. assistant chatbot - unable to actually make tasks or reminders. Telegram interface in this assistance will need a yes / no option for allowing creation of tasks/reminders/memories.

~~2. When interacting with searched memory (image with no description), the telegram buttons all don't respond except for delete.~~

~~3. When using natural language to set a reminder, the LLM does properly send a proposed time to which the user accepts. But the system then overrides it and follows up with a prompt asking for the time to set.~~

## Minor
1. Editing tags on pictures seem to add them. This needs to be better managed ( edit vs add vs delete tags )

# Feature / Updates
## Important
1. Need better visualisation of current queue. Since this system relies on local models which are not stable, there needs to be a more robust handling mechanism in the system to deal with periods of unavailability or failures. 

~~2. Timezone setting, all timestamps to include timezone, even when sending back responses to user.~~

~~3. When setting reminders or tasks, if regex check fails for proper timestamp format, fallback to LLM processing to generate a timestamp from the user's response.~~

## Minor
1. Better visualisation of assistant worldview of user.
2. Code cleanup
  - Magic numbers, define constants centrally
  - simplifying complex areas