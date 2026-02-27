# Bug list

## Critical
1. Natural language prompts not working properly. There was a follow up trigger that did specify a time to set the reminder, but when clicking on 'confirm', it did not actually save the reminder and changed to the `Select when to be reminded:` message instead. That behaviour is wrong. Extract of the text messages in telegram:
```
Jia Hui Yoong, [27/2/2026 4:52 PM]
Remind me to test in 5 minutes

TeleBearAssistant, [27/2/2026 4:52 PM]
Processing...

TeleBearAssistant, [27/2/2026 4:53 PM]
Could you clarify what you'd like to do? For example, are you setting a reminder, creating a task, searching for something, or just saving a note?

TeleBearAssistant, [27/2/2026 4:53 PM]
Select when to be reminded:

TeleBearAssistant, [27/2/2026 4:53 PM]
I couldn't process your request (followup). You can add tags or details manually.

TeleBearAssistant, [27/2/2026 4:54 PM]
I couldn't process your request (followup). You can add tags or details manually.
```
