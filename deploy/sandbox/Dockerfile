# The image the sandbox tool runs commands in, and the one attached files are parsed inside.
#
# It carries a shell, python, the file parsers and nothing else. No network reaches it at runtime,
# no credential is passed to it, and its workspace is a tmpfs the engine mounts.
FROM python:3.12-slim

# The parsers, and nothing that pulls them in. Pinned to what apps/engine declares.
RUN pip install --no-cache-dir --root-user-action=ignore \
        "pypdf>=5.1" \
        "python-docx>=1.1" \
        "python-pptx>=1.0" \
        "openpyxl>=3.1" \
    && find /usr/local -name '__pycache__' -type d -prune -exec rm -rf {} +

WORKDIR /opt/zipy

# The engine's own parsers. They import nothing from engine, so the text a file yields is the same
# whether it was read here or in the engine process.
COPY apps/engine/memory/ingest/parsers/errors.py parsers/errors.py
COPY apps/engine/memory/ingest/parsers/registry.py parsers/registry.py
COPY apps/engine/memory/ingest/parsers/text.py parsers/text.py
COPY apps/engine/memory/ingest/parsers/pdf.py parsers/pdf.py
COPY apps/engine/memory/ingest/parsers/office.py parsers/office.py
COPY apps/engine/memory/ingest/parsers/archive.py parsers/archive.py
COPY deploy/sandbox/extract.py extract.py

# registry.py and archive.py import the package by its engine path; inside the image it is parsers.
RUN printf '' > parsers/__init__.py \
    && sed -i 's/engine\.memory\.ingest\.parsers/parsers/g' parsers/*.py \
    && python -c "import sys; sys.path.insert(0, '/opt/zipy'); import extract" \
    && find /opt/zipy -name '__pycache__' -type d -prune -exec rm -rf {} +

ENV PYTHONPATH=/opt/zipy PYTHONDONTWRITEBYTECODE=1

# The engine runs `sh -c` against this image and mounts the workspace itself.
CMD ["sh"]
