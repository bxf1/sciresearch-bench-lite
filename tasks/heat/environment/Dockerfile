FROM sha256:6619dd1526ec8d635d0e57d068dc3e750821ddd82443d44777fe847340944bdb
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
