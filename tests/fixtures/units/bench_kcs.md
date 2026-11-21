# Batch inference jobs stuck in QUEUED

Source: confluence

## Issue

Batch inference jobs stay in the QUEUED state for more than an hour and never start.

## Cause

The scheduler's worker pool reached its quota after a configuration change lowered the per-tenant limit.

## Resolution

Raise the per-tenant worker quota back to its previous value in the scheduler configuration and restart the scheduler. Queued jobs start within five minutes.
