FROM sha256:29c3702340ac411f4051cd7f91782ff702491e09cb7dff6058b6604bc3405629
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
