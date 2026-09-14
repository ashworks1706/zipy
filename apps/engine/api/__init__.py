"""The HTTP surface: OAuth callbacks, provider webhooks, platform routes and health.

Runs in the same event loop as the platforms. Every provider and platform route is generic over
plugin names; a new plugin adds no route here.
"""
