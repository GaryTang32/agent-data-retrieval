"""Evidence store toolkit: record format, structure parsers, the content-addressed store,
structure-led chunks, the embedding cache and retrieval over the chunks.

The harness (`adr_eval`) stays separate; this package may import its text extraction,
tokenizer and corpus loading, never the other way round except through the system registry.
"""
