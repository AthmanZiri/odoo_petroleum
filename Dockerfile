FROM odoo:19

# The Bank PDF → CSV wizard reads statements with `pdftotext -layout`, which
# preserves the column positions its parsers use to tell a debit from a credit.
# The stock Odoo image ships no poppler, so the wizard cannot read any PDF.
USER root
COPY addons/mcp_server/requirements.txt /tmp/mcp_server-requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /tmp/mcp_server-requirements.txt \
    && rm /tmp/mcp_server-requirements.txt
USER odoo
