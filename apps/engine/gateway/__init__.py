"""The platform-neutral front door. Every platform hands messages here and renders what comes back.

The gateway resolves the workspace to an org and the sender to a role, applies the rate limit,
runs admin commands itself, sends everything else to the agent, and returns outbound messages
that fit the platform's capabilities. It never imports a platform.
"""
