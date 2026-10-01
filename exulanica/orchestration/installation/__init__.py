"""A complete installation's operations: custody of recovery authority, backups and maintenance.

This package composes the deletion, database and store boundaries into the procedures an
installation runs unattended, and sits in the orchestration layer because it does. The profile
loader and the facts the API serves are below it, in :mod:`exulanica.api.installation`.
"""
