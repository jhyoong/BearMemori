# Bug list

## Critical
1. Natural language prompts not working properly for search. When asked to `Search for all images about anime`, the system added a memory instead of searching. It should have been an LLM trigger to decide what kind of search to do, and return the best results. 