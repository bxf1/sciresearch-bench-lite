FROM sha256:c01f7a36320ffbba34200c5b04a1aeb55053641440b2fcaaa6c4555189a89f11
USER root
RUN rm -rf /input /opt/bench && mkdir -p /input /opt/bench
COPY public-dev/ /input/
COPY public/ /opt/bench/public/
COPY helpers/ /opt/bench/
COPY trusted/ /opt/bench/trusted/
RUN chown -R root:root /input /opt/bench && chmod -R a-w /input /opt/bench && cp /opt/bench/public/bench /usr/local/bin/bench && chmod 755 /usr/local/bin/bench
USER researcher
WORKDIR /workspace
CMD ["sleep", "infinity"]
