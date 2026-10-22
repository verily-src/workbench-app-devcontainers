FROM gitlabregistry.pep.cs.ru.nl/pep-public/core/ppp-prod

RUN apt-get update \
    && apt-get install -y --no-install-recommends sudo \
    && rm -rf /var/lib/apt/lists/*

# Create jupyter user (uid 1001) to match workbench expectations
RUN groupadd --gid 1001 jupyter \
    && useradd --uid 1001 --gid 1001 -m -s /bin/bash jupyter
