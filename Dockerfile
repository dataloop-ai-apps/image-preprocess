## Base
FROM hub.dataloop.ai/dtlpy-runner-images/cpu:python3.12_opencv

USER root

# OS deps: GDAL + headers + build toolchain + locales
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    gdal-bin libgdal-dev \
    build-essential python3-dev pkg-config \
    locales \
 && rm -rf /var/lib/apt/lists/*

# Locale
RUN locale-gen en_US.UTF-8
ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV LANGUAGE=en_US:en

# IMPORTANT: install Python GDAL bindings matching the system libgdal,
# then install rasterio (which depends on GDAL)
RUN set -eux; \
    GDAL_VERSION="$(gdal-config --version)"; \
    ${DL_PYTHON_EXECUTABLE} -m pip install --no-cache-dir \
        --index-url https://artifacts.dell.com/artifactory/api/pypi/python/simple \
        --trusted-host artifacts.dell.com \
        "GDAL==${GDAL_VERSION}.*"; \
    ${DL_PYTHON_EXECUTABLE} -m pip install --no-cache-dir \
        --index-url https://artifacts.dell.com/artifactory/api/pypi/python/simple \
        --trusted-host artifacts.dell.com \
        rasterio

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Drop privileges only AFTER installs
USER 1000

# docker build --no-cache -t  gcr.io/viewo-g/piper/agent/runner/apps/image-preprocess:0.0.1 -f Dockerfile .
