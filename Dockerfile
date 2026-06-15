FROM hub.dataloop.ai/dtlpy-runner-images/cpu:python3.12_opencv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#docker build --no-cache -t gcr.io/viewo-g/piper/agent/cpu/image-preprocess:6 -f Dockerfile .