FROM gitlabregistry.pep.cs.ru.nl/pep-public/core/ppp-prod

# Create jupyter user (uid 1001) to match workbench expectations
RUN groupadd --gid 1001 jupyter \
    && useradd --uid 1001 --gid 1001 -m -s /bin/bash jupyter

USER jupyter

RUN pip install --user --no-cache-dir jupyterlab jupyterlab-git

RUN mkdir -p /home/jupyter/.jupyter && cat > /home/jupyter/.jupyter/jupyter_server_config.py <<'EOF'
c.ServerApp.allow_origin = '*'
c.ServerApp.ip = '0.0.0.0'
c.ServerApp.token = ''
c.ServerApp.password = ''
c.ServerApp.root_dir = '/home/jupyter'
EOF

USER root
