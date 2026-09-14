"""Tool plugins: what the model can call. One folder per integration, each a BaseTool.

A tool folder holds tool.py (the BaseTool), client.py (the provider API), schemas.py (params,
results, settings) and tests/. A tool that produces searchable documents also implements
documents(). Tools never import each other.
"""
