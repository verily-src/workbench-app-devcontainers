c = get_config()

# Disable authentication
c.ServerApp.certfile=''
c.ServerApp.keyfile=''
c.IdentityProvider.token = ''
c.ServerApp.password = ''

# Disable quit button
c.ServerApp.quit_button=False
# Disable open browser on start
c.ServerApp.open_browser = False

# Set root directory
c.ServerApp.root_dir = '/home/jupyter'

# Set default shell
c.LabApp.terminado_settings = {'shell_command': ['/bin/bash']}

# Expose port
c.ServerApp.port = 8888
c.ServerApp.ip = '0.0.0.0'
c.ServerApp.disable_check_xsrf = True #see https://github.com/nteract/hydrogen/issues/922
c.ServerApp.allow_origin = '*'
