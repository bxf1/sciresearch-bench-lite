FROM sciresearch-numeric:0.3.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends bash curl ca-certificates git coreutils xz-utils && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /workspace /input /logs/agent /logs/artifacts /logs/verifier
WORKDIR /workspace
CMD ["sleep", "infinity"]
