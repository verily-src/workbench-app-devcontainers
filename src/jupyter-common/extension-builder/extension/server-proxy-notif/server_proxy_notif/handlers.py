import json
import getpass
import re
import subprocess
import logging
from typing import Set, Optional, Tuple
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join
import tornado
from tornado.process import Subprocess
from tornado.gen import with_timeout
from datetime import timedelta

logger = logging.getLogger(__name__)


class PortMonitorHandler(APIHandler):
    """Handler for monitoring listening ports"""

    @tornado.web.authenticated
    async def get(self):
        """Get currently listening ports asynchronously"""
        try:
            # Check if jupyter-server-proxy is installed
            try:
                import jupyter_server_proxy
                logger.debug('jupyter-server-proxy is available')
            except ImportError:
                logger.warning('jupyter-server-proxy is not installed, returning empty port list')
                self.finish(json.dumps({
                    'ports': [],
                    'warning': 'jupyter-server-proxy not installed'
                }))
                return

            logger.info('Port monitor API called')
            ports, warning = await self._get_listening_ports()
            logger.info(f'Found {len(ports)} listening ports: {sorted(ports)}')
            response = {'ports': list(ports)}
            if warning:
                response['warning'] = warning
            self.finish(json.dumps(response))
        except Exception as e:
            logger.error(f'Error getting listening ports: {e}', exc_info=True)
            self.set_status(500)
            self.finish(json.dumps({
                'error': str(e)
            }))

    async def _get_listening_ports(self) -> Tuple[Set[int], Optional[str]]:
        """Get list of listening ports using lsof asynchronously (user-owned only)

        Returns:
            tuple: (set of port numbers, warning message or None)
        """
        ports = set()
        warning = None

        # Get current username
        username = getpass.getuser()

        # Use lsof to find listening TCP ports owned by current user
        # -a means AND (combine conditions)
        # -u $USER shows only current user's processes
        # -i TCP -s TCP:LISTEN shows only listening TCP sockets
        # -P prevents port name resolution (shows numbers)
        # -n prevents hostname resolution (faster)
        try:
            process = Subprocess(
                ['lsof', '-a', '-u', username, '-i', 'TCP', '-s', 'TCP:LISTEN', '-P', '-n'],
                stdout=Subprocess.STREAM,
                stderr=Subprocess.STREAM
            )
        except FileNotFoundError:
            logger.warning('lsof command not found, cannot detect listening ports')
            warning = 'lsof not installed'
            return ports, warning

        try:
            await with_timeout(timedelta(seconds=5), process.wait_for_exit(raise_error=True))
        except tornado.gen.TimeoutError:
            process.proc.kill()
            await process.wait_for_exit(raise_error=False)
            logger.warning('lsof command timed out')
            warning = 'lsof timed out'
            return ports, warning
        except subprocess.CalledProcessError as e:
            # lsof may return exit code 1 if no results found, which is fine
            if e.returncode != 1:
                raise
            return ports, warning

        # Parse lsof output
        # Example line: python3  12345 user   3u  IPv4 0x1234  0t0  TCP *:8080 (LISTEN)
        #               python3  12345 user   3u  IPv4 0x1234  0t0  TCP 127.0.0.1:8080 (LISTEN)
        output = (await process.stdout.read_until_close()).decode('utf-8')
        for line in output.split('\n'):
            if 'LISTEN' in line:
                # Extract port from patterns like:
                # *:PORT, 127.0.0.1:PORT, localhost:PORT, [::]:PORT
                # Port is always after the last colon before (LISTEN)
                match = re.search(r':(\d+)\s+\(LISTEN\)', line)
                if match:
                    ports.add(int(match.group(1)))

        return ports, warning


def setup_handlers(web_app):
    """Setup the handlers for the server extension"""
    host_pattern = ".*$"
    base_url = web_app.settings["base_url"]

    route_pattern = url_path_join(base_url, "server-proxy-notif", "ports")
    handlers = [(route_pattern, PortMonitorHandler)]
    web_app.add_handlers(host_pattern, handlers)

    logger.info(f"Registered server-proxy-notif handler at: {route_pattern}")
