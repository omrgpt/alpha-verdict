FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN python -m pip install .

RUN groupadd --system alphaverdict \
    && useradd --system --gid alphaverdict --create-home alphaverdict \
    && mkdir /workspace \
    && chown alphaverdict:alphaverdict /workspace

USER alphaverdict
WORKDIR /workspace

ENTRYPOINT ["alphaverdict"]
CMD ["--help"]
