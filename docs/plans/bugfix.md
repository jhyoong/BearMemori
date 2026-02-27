---                                                                                                                                                                                                     
  Bug 1: LLM Timeout Does Not Retry                                                                                                                                                                       
                                                                                                                                                                                                          
  Root cause: consume() in redis_streams.py:86 always uses XREADGROUP with ">" as the ID. This exclusively delivers new messages — it never re-delivers messages that are in the Pending Entry List (PEL).
   When a job fails (either UNAVAILABLE or INVALID_RESPONSE), the message is intentionally not ACK'd so it stays in the PEL. But on the next consumer loop iteration, consume(stream, ">" ...) skips over
  it entirely. Pending messages are never re-claimed.

  The asyncio.sleep(backoff) at consumer.py:201 does nothing useful — it delays before returning, then the loop still fetches only new messages. Neither failure type actually gets retried.

  Fix needed: The consumer needs a second read pass using XREADGROUP with "0" (or XAUTOCLAIM) to pick up its own pending/idle messages before reading new ones.

  ---
  Bug 2: Reminder Time Not Extracted from Natural Language

  Root cause: Field name mismatch between IntentHandler and the Telegram consumer.

  IntentHandler (intent.py) returns resolved_time for reminders and resolved_due_time for tasks. The Telegram gateway consumer (consumer.py:219) reads content.get("extracted_datetime"). That key never
  exists in the result — it is always None.

  Consequence: the displayed proposal always says "at unspecified time" and the user must manually pick a time, discarding the LLM's resolved time entirely.

  Fix needed: In consumer.py:_handle_intent_result(), replace the extracted_datetime lookup with intent-specific field names: resolved_time for reminder, resolved_due_time for task.

  ---
  Bug 3: Search Query Not Working Naturally

  Root cause: Two separate problems:

  1. The intent handler never performs a search. IntentHandler.handle() classifies intent and returns "results": [] — it never calls the Core API search endpoint. The consumer receives an empty list and
   immediately shows "No results found."
  2. Field name mismatch. The intent handler returns the field as results, but the consumer reads content.get("search_results", []) (consumer.py:222). Even if results were populated, they would not be
  read.

  The unnatural query text (e.g., "all images about anime") comes from the LLM's query field in the intent result, which is set to the original raw message text in intent.py:41 ("query": message) before
   being overwritten by the LLM response — which may or may not clean it up.

  Fix needed: After intent classification returns search, the handler must call the search API with the extracted keywords and return the results under a consistent field name.

  ---
  Bug 4: Reminders Saved as Tasks

  Root cause: _parse_callback_data() in callback.py:164-169 has an ambiguous "custom" check:

  if choice in ("today", "tomorrow", "next_week", "no_date", "custom"):
      return DueDateChoice(...)          # task flow
  elif choice in ("1h", "tomorrow_9am", "custom"):
      return ReminderTimeChoice(...)     # reminder flow

  "custom" appears in both sets. The DueDateChoice check runs first, so clicking "Custom" on reminder_time_keyboard is always parsed as DueDateChoice. Control goes to handle_due_date_choice() which sets
   PENDING_TASK_MEMORY_ID and ultimately creates a Task instead of a Reminder.

  The 1h and tomorrow_9am choices work correctly because they are not in the DueDateChoice set. Only the "Custom" path is broken.

  Secondary issue: The LLM prompt's distinction between reminder and task is weak (both involve time), which can cause misclassification upstream, but the "custom" parsing bug is the concrete code
  defect.

  Fix needed: Disambiguate the callback parsing — either use a type discriminator field in the serialized callback data, or move "custom" out of the DueDateChoice set and rely on context.