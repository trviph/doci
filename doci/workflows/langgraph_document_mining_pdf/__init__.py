"""PDF document-mining child workflow.

Split a PDF into pages and process each independently: pure-text pages go through
the text path (extract → annotate → minimap thumbnail); pages with images,
annotations/widgets, or no extractable text are rendered to PNG and run through
the image child workflow.
"""
