FROM sciresearch-numeric:0.3.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends bash curl ca-certificates git coreutils xz-utils && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 --shell /bin/bash researcher && mkdir -p /workspace/.bench/requests /workspace/.bench/responses /input /opt/bench/public /logs/agent /logs/artifacts /run/bench-export && chmod 1777 /workspace && chmod 700 /run/bench-export && chown researcher:researcher /workspace/.bench/requests /logs/agent /logs/artifacts
COPY public-dev/ /input/
COPY public/ /opt/bench/public/
COPY helpers/ /opt/bench/
COPY trusted/ /opt/bench/trusted/
RUN chmod -R a-w /input /opt/bench && cp /opt/bench/public/bench /usr/local/bin/bench && chmod 755 /usr/local/bin/bench
ENV HOME=/home/researcher PYTHONPATH=/opt/bench
USER researcher
WORKDIR /workspace
CMD ["sleep", "infinity"]
