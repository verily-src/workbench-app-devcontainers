FROM projectmonai/monailabel:0.8.0

WORKDIR /workspace

# Copy requirements file
COPY segmentationMonaiLabel/apps/monaibundle/requirements.txt /workspace/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Create necessary directories
RUN mkdir -p /workspace/apps
COPY segmentationMonaiLabel/apps /workspace/apps

# Expose port
EXPOSE 8000

CMD ["monailabel" "start_server" "--app" "apps/monaibundle" "--conf" "bundles" "IntegrationBundle,SegformerBundle,MedSamBundle" "--conf" "zoo_source" "ngc"]
# CMD ["echo", "hooked up"]