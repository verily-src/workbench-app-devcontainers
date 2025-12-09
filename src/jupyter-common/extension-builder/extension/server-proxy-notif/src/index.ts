import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Notification } from '@jupyterlab/apputils';
import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

/**
 * Port monitoring state
 */
class PortMonitor {
  private _knownPorts: Set<number> = new Set();
  private _pollInterval: number = 3000; // Poll every 3 seconds
  private _intervalId: number | null = null;
  private _serverSettings: ServerConnection.ISettings;

  constructor(serverSettings: ServerConnection.ISettings) {
    this._serverSettings = serverSettings;
  }

  /**
   * Start monitoring ports
   */
  async start(): Promise<boolean> {
    if (this._intervalId !== null) {
      return false;
    }

    // Initial check to populate known ports
    if (!(await this._checkPorts())) {
      console.log('Port monitoring not started');
      return false;
    }

    // Set up polling
    this._intervalId = window.setInterval(() => {
      this._checkPorts();
    }, this._pollInterval);

    return true;
  }

  /**
   * Stop monitoring ports
   */
  stop(): void {
    if (this._intervalId !== null) {
      window.clearInterval(this._intervalId);
      this._intervalId = null;
    }
  }

  /**
   * Check for new listening ports
   * @param isInitial - If true, don't notify about ports (just populate the baseline)
   */
  private async _checkPorts(): Promise<boolean> {
    try {
      const url = URLExt.join(
        this._serverSettings.baseUrl,
        'server-proxy-notif',
        'ports'
      );

      const response = await ServerConnection.makeRequest(
        url,
        {},
        this._serverSettings
      );

      if (!response.ok) {
        console.warn(
          'Failed to fetch port status:',
          response.status,
          response.statusText
        );
        const text = await response.text();
        console.warn('Response body:', text);
        return false;
      }

      const data = await response.json();

      // Check if jupyter-server-proxy is installed
      if (data.warning) {
        console.warn(data.warning);
        return false;
      }

      const currentPorts = new Set<number>(data.ports || []);

      if (this._knownPorts.size > 0) {
        // Find newly opened ports
        const newPorts = Array.from(currentPorts).filter(
          port => !this._knownPorts.has(port)
        );

        // Notify about new ports
        newPorts.forEach(port => {
          this._notifyNewPort(port);
        });
      }

      // Update known ports
      this._knownPorts = currentPorts;
    } catch (error) {
      console.error('Error checking ports:', error);
      return false;
    }
    return true;
  }

  /**
   * Show notification for a new port
   */
  private _notifyNewPort(port: number): void {
    const proxyUrl = `/proxy/${port}/`;

    Notification.emit(`Port opened at :${port}. View at ${proxyUrl}`, 'info', {
      autoClose: 10000,
      actions: [
        {
          label: 'Open',
          callback: () => {
            window.open(proxyUrl, '_blank');
          }
        }
      ]
    });

    console.log(
      `New server detected on port ${port}. Proxy available at: ${proxyUrl}`
    );
  }
}

/**
 * Initialization data for the server-proxy-notif extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'server-proxy-notif:plugin',
  description: 'Notify server proxy ports',
  autoStart: true,
  activate: (_app: JupyterFrontEnd) => {
    console.log('JupyterLab extension server-proxy-notif is activated!');

    // Create and start port monitor
    const serverSettings = ServerConnection.makeSettings();
    const portMonitor = new PortMonitor(serverSettings);
    portMonitor.start().then(started => {
      if (started) {
        console.log(
          'Port monitoring started - checking for newly opened ports every 3 seconds'
        );
      }
    });
  }
};

export default plugin;
