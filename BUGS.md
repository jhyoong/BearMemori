# Bug list

## Critical
1. Natural language prompts not working properly for search. When asked to `Search for all images about anime`, the old memory that was caused by the previous bug still exists. It also cannot be deleted through the telegram interface, even when the delete button was shown. Also, it doesn't intelligently search for the actual memory, the one that was tagged with 'anime', but rather, the search became specifically `Search results for "all images about anime":` which doesn't properly answer the user's query.