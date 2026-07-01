# Clean-host install rehearsal for quner: install the built wheel into a bare
# container and exercise the non-privileged, capability-detecting paths. A
# container has no cpufreq/RAPL/nvidia of its own, so this proves quner installs
# cleanly and degrades fail-loud (every lever "unavailable") on a foreign host.
FROM python:3.12-slim

WORKDIR /opt/quner
COPY dist/ /opt/quner/dist/
RUN pip install --no-cache-dir /opt/quner/dist/*.whl

# Non-privileged smoke test at build time.
RUN quner --version \
    && quner doctor \
    && quner install --dry-run

CMD ["quner", "doctor"]
