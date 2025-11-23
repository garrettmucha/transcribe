FROM ubuntu:22.04

RUN apt-get update && apt-get install -y wget tar && \
    wget https://github.com/deroproject/derohe/releases/download/v3.6.9/dero_linux_amd64.tar.gz && \
    tar -xzf dero_linux_amd64.tar.gz && \
    mv dero-linux-amd64-3.6.9/dero-miner-linux-amd64 /usr/local/bin/dero-miner && \
    chmod +x /usr/local/bin/dero-miner && \
    rm -rf dero_linux_amd64.tar.gz dero-linux-amd64-3.6.9 && \
    apt-get clean

ENTRYPOINT ["/usr/local/bin/dero-miner"]
