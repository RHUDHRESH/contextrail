"""The agentic core (CLAUDE.md §25, D-014): the seams the model-facing features use, and their read-only tools.

Memory and RAG feed evidence and answers; the tools a model may call are read-only; policy still reads records only,
and no model output sets a verdict, an approval or `verified`.
"""
