FROM gitlabregistry.pep.cs.ru.nl/pep-public/core/ppp-prod

# Create jupyter user (uid 1001) to match workbench expectations
RUN groupadd --gid 1001 jupyter \
    && useradd --uid 1001 --gid 1001 -m -s /bin/bash jupyter
