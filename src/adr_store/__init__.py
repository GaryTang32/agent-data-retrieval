"""Evidence store toolkit: record format, structure parsers and the content-addressed store.

The harness (`adr_eval`) stays separate; this package may import its text extraction,
tokenizer and corpus loading, never the other way round except through the system registry.
"""
