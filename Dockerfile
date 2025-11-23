FROM ubuntu:22.04

RUN apt-get update && apt-get install -y wget tar && \
    wget https://github.com/deroproject/derohe/releases/latest/download/dero_linux_amd64.tar.gz && \
    tar -xzf dero_linux_amd64.tar.gz && \
    ls -la && \
    find . -name "*miner*" -type f && \
    cp $(find . -name "dero-miner-linux-amd64" -type f) /usr/local/bin/dero-miner && \
    chmod +x /usr/local/bin/dero-miner && \
    rm -rf dero_linux_amd64.tar.gz dero-linux-amd64-* dero_linux_amd64 && \
    apt-get clean

ENTRYPOINT ["/usr/local/bin/dero-miner"]
