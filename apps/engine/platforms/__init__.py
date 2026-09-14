"""Platform plugins: one folder per chat platform Zipy lives on, each a BasePlatform.

A platform translates its events into gateway messages and renders gateway output. It knows
nothing about orgs, tools or models. Platforms never import each other.
"""
