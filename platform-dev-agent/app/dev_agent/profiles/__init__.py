"""Persona package: ``ProfileBase`` + auto-discovered personas.

The 8 personas (security, qa_engineer, architecture, backend, frontend, devops,
product_owner, product_manager) are minimal subclasses; their metadata and
prompt live in ``knowledge/profiles/<id>.md``. :mod:`registry` populates
``PROFILES`` by cross-checking classes against those files.
"""
