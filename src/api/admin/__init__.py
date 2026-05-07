"""Admin-only API surface (RBAC management).

Every endpoint in this package is gated by `require_permission(...)` and
writes an `audit_log` row in the same transaction as its mutation.
"""
