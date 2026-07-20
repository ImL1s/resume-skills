# Linux peer OS gate report

Host OS: macOS-26.4-arm64-arm-64bit-Mach-O

docker binary: /usr/local/bin/docker
docker info exit: 1
docker daemon unavailable; stderr head:
Cannot connect to the Docker daemon at unix:///Users/iml1s/.docker/run/docker.sock. Is the docker daemon running?


## Verdict: Linux deterministic gate **NOT RUN / FAILED TO START**
Do **not** claim AC-18 dual-OS release. macOS deterministic bar remains separately proven.
