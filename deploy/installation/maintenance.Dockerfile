# The maintenance image: the backend image, plus the PostgreSQL 18 client and server programs that
# a backup set needs (pg_dump, and a scratch server that proves a set restores).
#
# The backend image is Debian trixie and has no PostgreSQL programs; Debian trixie packages
# PostgreSQL 17, and pg_dump must be at least the server's version. The programs are therefore
# copied from the pgvector image the database already runs (bookworm), with the shared libraries
# they link, into a private directory that only the PostgreSQL processes load, through wrappers.
# glibc and the C++ runtime are not copied: trixie's are newer and backward compatible. The JIT
# module is left out with the LLVM it would need, so the scratch server runs without JIT.
#
# Built by compose.yaml's maintenance service, which supplies the backend image as the `backend`
# build context.

# Every base is its version's multi-platform index by digest, the tag kept in the name for the reader:
# a build never resolves a moving tag, and one whose base is already held needs no registry
# (tests/test_base_images_pinned.py).
FROM pgvector/pgvector:0.8.6-pg18@sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a AS postgresql
RUN set -eu; \
    rm -f /usr/lib/postgresql/18/lib/llvmjit*; \
    rm -rf /usr/lib/postgresql/18/lib/bitcode; \
    mkdir -p /opt/postgresql/lib; \
    for program in /usr/lib/postgresql/18/bin/* /usr/lib/postgresql/18/lib/*.so; do \
      ldd "$program" 2>/dev/null | awk '/=>/ {print $3}'; \
    done | sort -u \
      | grep -vE '/(libc|libm|libpthread|libdl|librt|libresolv|ld-linux[^/]*|libgcc_s|libstdc\+\+)[.-]' \
      | while read -r library; do cp -L "$library" /opt/postgresql/lib/; done

FROM backend
USER root
COPY --from=postgresql /usr/lib/postgresql/18 /usr/lib/postgresql/18
COPY --from=postgresql /usr/share/postgresql /usr/share/postgresql
COPY --from=postgresql /usr/share/zoneinfo /usr/share/zoneinfo
# The database's own locale, en_US.UTF-8, which a restored dump's database names and the scratch
# server must therefore have; the slim backend image carries no locale data.
COPY --from=postgresql /usr/lib/locale/locale-archive /usr/lib/locale/locale-archive
COPY --from=postgresql /opt/postgresql/lib /opt/postgresql/lib
RUN set -eu; \
    mkdir -p /opt/postgresql/bin; \
    for name in initdb pg_ctl postgres pg_dump pg_restore psql pg_isready; do \
      printf '#!/bin/sh\nLD_LIBRARY_PATH=/opt/postgresql/lib exec /usr/lib/postgresql/18/bin/%s "$@"\n' \
        "$name" > "/opt/postgresql/bin/$name"; \
      chmod 755 "/opt/postgresql/bin/$name"; \
    done; \
    /opt/postgresql/bin/postgres --version; \
    /opt/postgresql/bin/pg_dump --version; \
    LC_ALL=en_US.UTF-8 python -c "import locale; locale.setlocale(locale.LC_ALL, '')"
ENV EXULANICA_POSTGRES_BIN=/opt/postgresql/bin
USER exulanica

# Healthy while the status file is newer than fifteen minutes. Nothing restarts an unhealthy
# container: Docker and Compose only mark it, and `restart: unless-stopped` acts on an exit. The
# status file's failures are what an operator reads.
HEALTHCHECK --interval=60s --timeout=5s --start-period=300s --retries=3 \
  CMD ["python", "-c", "import json,sys,datetime as d; s=json.load(open('/var/lib/exulanica-status/maintenance.json')); sys.exit(0 if d.datetime.now(d.UTC)-d.datetime.fromisoformat(s['written_at'])<d.timedelta(minutes=15) else 1)"]

CMD ["exulanica-installation", "maintenance", "--loop"]
