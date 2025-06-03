import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { addIcon, copyIcon, downloadIcon } from '@jupyterlab/ui-components';
import { IFileBrowserFactory, FileBrowser } from '@jupyterlab/filebrowser';
import { IDocumentManager } from '@jupyterlab/docmanager';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import {
  Clipboard,
  Dialog,
  ICommandPalette,
  SemanticCommand,
  showDialog,
  WidgetTracker,
  InputDialog
} from '@jupyterlab/apputils';
import { IMainMenu } from '@jupyterlab/mainmenu';
import { PageConfig } from '@jupyterlab/coreutils';
import { INotebookTracker } from '@jupyterlab/notebook';
import { map } from '@lumino/algorithm';
import { Menu, PanelLayout, Widget } from '@lumino/widgets';
import { Contents } from '@jupyterlab/services';

// downloadPlugin from https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/src/index.ts
const filebrowserDownloadPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyterlab:filebrowser-download',
  description:
    'Adds the download file commands. Disabling this plugin will NOT disable downloading files from the server, if the user enters the appropriate download URLs.',
  requires: [IFileBrowserFactory, ITranslator],
  autoStart: true,
  activate: (
    app: JupyterFrontEnd,
    factory: IFileBrowserFactory,
    translator: ITranslator
  ) => {
    const trans = translator.load('jupyterlab');
    const { commands } = app;
    const { tracker } = factory;

    commands.addCommand('filebrowser:download', {
      execute: async () => {
        const widget = tracker.currentWidget;
        if (!widget) {
          return;
        }

        if (!(await downloadPolicyPopUp())) {
          return;
        }

        return Promise.all(
          Array.from(widget.selectedItems())
            .filter(item => item.type !== 'directory')
            .map(async (item): Promise<void> => {
              const url = affirmUrl(
                await widget.model.manager.services.contents.getDownloadUrl(
                  item.path
                )
              );
              downloadUrl(url);
            })
        );
      },
      icon: downloadIcon.bindprops({ stylesheet: 'menuItem' }),
      label: trans.__('Download')
    });

    commands.addCommand('filebrowser:copy-download-link', {
      execute: async () => {
        const widget = tracker.currentWidget;
        if (!widget) {
          return;
        }

        if (!(await downloadPolicyPopUp())) {
          return;
        }

        const url = affirmUrl(
          await widget.model.manager.services.contents.getDownloadUrl(
            widget.selectedItems().next()!.value.path
          )
        );
        Clipboard.copyToSystem(url);
      },
      isVisible: () =>
        // So long as this command only handles one file at time, don't show it
        // if multiple files are selected.
        !!tracker.currentWidget &&
        Array.from(tracker.currentWidget.selectedItems()).length === 1,
      icon: copyIcon.bindprops({ stylesheet: 'menuItem' }),
      label: trans.__('Copy Download Link'),
      mnemonic: 0
    });

    // downloadPlugin context menu buttons from
    // https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/schema/download.json
    app.contextMenu.addItem({
      command: 'filebrowser:download',
      selector: '.jp-DirListing-item[data-isdir="false"]',
      rank: 9
    });

    app.contextMenu.addItem({
      command: 'filebrowser:copy-download-link',
      selector: '.jp-DirListing-item[data-isdir="false"]',
      rank: 13
    });
  }
};

// openBrowserTabPlugin from https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/src/index.ts
const filebrowserOpenBrowserTabPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyterlab:filebrowser-open-browser-tab',
  description: 'Adds the open-in-new-browser-tab features.',
  requires: [IFileBrowserFactory, ITranslator],
  autoStart: true,
  activate: (
    app: JupyterFrontEnd,
    factory: IFileBrowserFactory,
    translator: ITranslator
  ) => {
    const trans = translator.load('jupyterlab');
    const { commands } = app;
    const { tracker } = factory;

    commands.addCommand('filebrowser:open-browser-tab', {
      execute: async args => {
        const widget = tracker.currentWidget;

        if (!widget) {
          return;
        }

        const mode = args['mode'] as string | undefined;

        if (!(await downloadPolicyPopUp())) {
          return;
        }

        return Promise.all(
          Array.from(
            map(widget.selectedItems(), item => {
              if (mode === 'single-document') {
                const url = PageConfig.getUrl({
                  mode: 'single-document',
                  treePath: item.path
                });
                const opened = window.open();
                if (opened) {
                  opened.opener = null;
                  opened.location.href = affirmUrl(url);
                } else {
                  throw new Error('Failed to open new browser tab.');
                }
              } else {
                return commands.execute('docmanager:open-browser-tab', {
                  path: item.path,
                  affirmed: true
                });
              }
            })
          )
        );
      },
      icon: addIcon.bindprops({ stylesheet: 'menuItem' }),
      label: args =>
        args['mode'] === 'single-document'
          ? trans.__('Open in Simple Mode')
          : trans.__('Open in New Browser Tab'),
      mnemonic: 0
    });

    // openBrowserTabPlugin context menu buttons from
    // https://github.com/jupyterlab/jupyterlab/blob/main/packages/filebrowser-extension/schema/open-browser-tab.json
    app.contextMenu.addItem({
      command: 'filebrowser:open-browser-tab',
      selector: '.jp-DirListing-item[data-isdir="false"]',
      rank: 1.6
    });
  }
};

// downloadPlugin from https://github.com/jupyterlab/jupyterlab/blob/main/packages/docmanager-extension/src/index.ts
const docmanagerDownloadPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyterlab:docmanager-download',
  description: 'Adds command to download files.',
  autoStart: true,
  requires: [IDocumentManager],
  optional: [IMainMenu, ITranslator, ICommandPalette],
  activate: (
    app: JupyterFrontEnd,
    docManager: IDocumentManager,
    mainMenu: IMainMenu | null,
    translator: ITranslator | null,
    palette: ICommandPalette | null
  ) => {
    const trans = (translator ?? nullTranslator).load('jupyterlab');
    const { commands, shell } = app;
    const isEnabled = () => {
      const { currentWidget } = shell;
      return !!(currentWidget && docManager.contextForWidget(currentWidget));
    };
    commands.addCommand('docmanager:download', {
      label: trans.__('Download'),
      caption: trans.__('Download the file to your computer'),
      isEnabled,
      execute: async () => {
        // Checks that shell.currentWidget is valid:
        if (!isEnabled()) {
          return;
        }

        if (!(await downloadPolicyPopUp())) {
          return;
        }

        const context = docManager.contextForWidget(shell.currentWidget!);
        if (!context) {
          return showDialog({
            title: trans.__('Cannot Download'),
            body: trans.__('No context found for current widget!'),
            buttons: [Dialog.okButton()]
          });
        }
        const url = affirmUrl(
          await docManager.services.contents.getDownloadUrl(context.path)
        );
        downloadUrl(url);
      }
    });

    app.shell.currentChanged?.connect(() => {
      app.commands.notifyCommandChanged('docmanager:download');
    });

    const category = trans.__('File Operations');
    if (palette) {
      palette.addItem({ command: 'docmanager:download', category });
    }

    // downloadPlugin menu buttons from
    // https://github.com/jupyterlab/jupyterlab/blob/main/packages/docmanager-extension/schema/download.json
    if (mainMenu) {
      mainMenu.fileMenu.addGroup([{ command: 'docmanager:download' }], 6);
    }
  }
};

// openBrowserTabPlugin from https://github.com/jupyterlab/jupyterlab/blob/main/packages/docmanager-extension/src/index.ts
const docmanagerOpenBrowserTabPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyterlab:docmanager-open-browser-tab',
  description: 'Adds command to open a browser tab.',
  autoStart: true,
  requires: [IDocumentManager],
  optional: [ITranslator],
  activate: (
    app: JupyterFrontEnd,
    docManager: IDocumentManager,
    translator: ITranslator | null
  ) => {
    const trans = (translator ?? nullTranslator).load('jupyterlab');
    const { commands } = app;
    commands.addCommand('docmanager:open-browser-tab', {
      execute: async args => {
        const path =
          typeof args['path'] === 'undefined' ? '' : (args['path'] as string);
        const affirmed = args['affirmed'] === true;

        if (!path) {
          return;
        }

        if (!affirmed && !(await downloadPolicyPopUp())) {
          return;
        }

        const url = affirmUrl(
          await docManager.services.contents.getDownloadUrl(path)
        );
        const opened = window.open();
        if (opened) {
          opened.opener = null;
          opened.location.href = url;
        } else {
          throw new Error('Failed to open new browser tab.');
        }
      },
      iconClass: args => (args['icon'] as string) || '',
      label: () => trans.__('Open in New Browser Tab')
    });
  }
};

const FORMAT_EXCLUDE = ['notebook', 'python', 'custom'];

// exportPlugin from https://github.com/jupyterlab/jupyterlab/blob/4.4.x/packages/notebook-extension/src/index.ts
const notebookExportPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyter:notebook-export',
  description: 'Adds the export notebook commands.',
  autoStart: true,
  requires: [ITranslator, INotebookTracker],
  optional: [IMainMenu, ICommandPalette],
  activate: (
    app: JupyterFrontEnd,
    translator: ITranslator,
    tracker: INotebookTracker,
    mainMenu: IMainMenu | null,
    palette: ICommandPalette | null
  ) => {
    const trans = translator.load('jupyterlab');
    const { commands, shell } = app;
    const services = app.serviceManager;

    const isEnabled = (): boolean => {
      return (
        tracker.currentWidget !== null &&
        tracker.currentWidget === shell.currentWidget
      );
    };

    const getFormatLabels = (
      translator: ITranslator
    ): {
      [k: string]: string;
    } => {
      translator = translator || nullTranslator;
      const trans = translator.load('jupyterlab');
      return {
        html: trans.__('HTML'),
        latex: trans.__('LaTeX'),
        markdown: trans.__('Markdown'),
        pdf: trans.__('PDF'),
        rst: trans.__('ReStructured Text'),
        script: trans.__('Executable Script'),
        slides: trans.__('Reveal.js Slides')
      };
    };

    commands.addCommand('notebook:export-to-format', {
      label: args => {
        if (args.label === undefined) {
          return trans.__('Save and Export Notebook to the given `format`.');
        }
        const formatLabel = args['label'] as string;
        return args['isPalette']
          ? trans.__('Save and Export Notebook: %1', formatLabel)
          : formatLabel;
      },
      execute: async args => {
        const current = args[SemanticCommand.WIDGET]
          ? (tracker.find(panel => panel.id === args[SemanticCommand.WIDGET]) ??
            null)
          : tracker.currentWidget;
        const activate = args['activate'] !== false;

        if (activate && current) {
          shell.activateById(current.id);
        }

        if (!current) {
          return;
        }

        if (!(await downloadPolicyPopUp())) {
          return;
        }

        const url = affirmUrl(
          PageConfig.getNBConvertURL({
            format: args['format'] as string,
            download: true,
            path: current.context.path
          })
        );
        const { context } = current;

        if (context.model.dirty && !context.model.readOnly) {
          return context.save().then(() => {
            window.open(url, '_blank', 'noopener');
          });
        }

        return new Promise<void>(resolve => {
          window.open(url, '_blank', 'noopener');
          resolve(undefined);
        });
      },
      isEnabled
    });

    // Add a notebook group to the File menu.
    let exportTo: Menu | null | undefined;
    if (mainMenu) {
      // export submenu from
      // https://github.com/jupyterlab/jupyterlab/blob/main/packages/notebook-extension/schema/export.json
      exportTo = new Menu({ commands: app.commands });
      exportTo.id = 'jp-mainmenu-file-notebookexport';
      exportTo.title.label = 'Save and Export Notebook As';
      mainMenu.fileMenu.addGroup([{ type: 'submenu', submenu: exportTo }], 10);
    }

    let formatsInitialized = false;

    /** Request formats only when a notebook might use them. */
    const maybeInitializeFormats = async () => {
      if (formatsInitialized) {
        return;
      }

      tracker.widgetAdded.disconnect(maybeInitializeFormats);

      formatsInitialized = true;

      const response = await services.nbconvert.getExportFormats(false);

      if (!response) {
        return;
      }

      const formatLabels: any = getFormatLabels(translator);

      // Convert export list to palette and menu items.
      const formatList = Object.keys(response);
      formatList.forEach(function (key) {
        const capCaseKey = trans.__(key[0].toUpperCase() + key.substring(1));
        const labelStr = formatLabels[key] ? formatLabels[key] : capCaseKey;
        let args = {
          format: key,
          label: labelStr,
          isPalette: false
        };
        if (FORMAT_EXCLUDE.indexOf(key) === -1) {
          if (exportTo) {
            exportTo.addItem({
              command: 'notebook:export-to-format',
              args: args
            });
          }
          if (palette) {
            args = {
              format: key,
              label: labelStr,
              isPalette: true
            };
            const category = trans.__('Notebook Operations');
            palette.addItem({
              command: 'notebook:export-to-format',
              category,
              args
            });
          }
        }
      });
    };

    tracker.widgetAdded.connect(maybeInitializeFormats);
  }
};

// The upload button is not part of a separate plugin that we can disable and
// replace easily. Instead we can override the upload function to show a prompt.
const uploadInterceptPlugin: JupyterFrontEndPlugin<void> = {
  id: 'aou-jupyterlab:upload-intercept',
  description: 'Intercepts the upload button to affirm AoU policy',
  requires: [IFileBrowserFactory],
  autoStart: true,
  activate: (_app: JupyterFrontEnd, factory: IFileBrowserFactory) => {
    const { tracker: fileTracker } = factory;

    const fileBrowserAdded = (
      _tracker: WidgetTracker<FileBrowser>,
      browser: FileBrowser
    ) => {
      const oldUpload = browser.model.upload.bind(browser.model);

      browser.model.upload = async function (
        file: File,
        path?: string
      ): Promise<Contents.IModel> {
        if (!(await uploadPolicyPopUp())) {
          throw new Error(
            'You must affirm the All of Us Data Use Policies to upload files.'
          );
        }

        return oldUpload(file, path);
      };
    };
    fileTracker.widgetAdded.connect(fileBrowserAdded);
    fileTracker.forEach(browser => fileBrowserAdded(fileTracker, browser));
  }
};

function affirmUrl(url: string) {
  return `${url}${url.includes('?') ? '&' : '?'}affirm=true`;
}

function downloadUrl(url: string) {
  const element = document.createElement('a');
  element.href = url;
  element.download = '';
  document.body.appendChild(element);
  element.click();
  document.body.removeChild(element);
}

async function uploadPolicyPopUp(): Promise<boolean> {
  const aff = await showDialog({
    title: 'Policy Reminder',
    body: 'The All of Us Data Use Policies prohibit you from uploading data or files containing personally identifiable information (PII). Any external data, files, or software that is uploaded into the Workspace should be exclusively for the research purpose that was provided for this Workspace.',
    buttons: [
      Dialog.cancelButton({ label: 'Cancel' }),
      Dialog.warnButton({ label: 'Continue' })
    ]
  });

  return aff.button.accept;
}

async function downloadPolicyPopUp(): Promise<boolean> {
  const aff = await InputDialog.getText({
    title: 'Policy Reminder',
    okLabel: 'Continue',
    pattern: `^${regexIgnoreCase('affirm')}$`,
    required: true,
    // InputDialog.getText is not very customizable, so we use a custom renderer
    // to add the policy text and change the footer buttons
    renderer: new DownloadPolicyRenderer()
  });

  const affirmed = aff.button.accept && aff.value?.toLowerCase() === 'affirm';

  if (!affirmed) {
    showDialog({
      title: 'Download Cancelled',
      body: 'You must affirm the All of Us Data Use Policies to download files.',
      buttons: [Dialog.okButton()]
    });
  }

  return affirmed;
}

function regexIgnoreCase(str: string): string {
  return str
    .split('')
    .map(char => `[${char.toLowerCase()}${char.toUpperCase()}]`)
    .join('');
}

// DownloadPolicyRenderer is a custom renderer that adds the policy text and
// changes the footer buttons to have a warning style.
class DownloadPolicyRenderer extends Dialog.Renderer {
  createBody(value: Dialog.Body<any>): Widget {
    const wrapper = new Widget({ node: document.createElement('div') });
    const layout = new PanelLayout();
    wrapper.layout = layout;

    const text = new Widget({ node: document.createElement('div') });

    [
      'The All of Us Data Use Policies prohibit you from removing participant-level data from the workbench. You are also prohibited from publishing or otherwise distributing any data or aggregate statistics corresponding to fewer than 20 participants unless expressly permitted by our data use policies.',
      'To continue, affirm that this download will be used in accordance with the All of Us data use policy by typing "affirm" below.'
    ].forEach((textContent, i) => {
      const p = document.createElement('p');
      p.textContent = textContent;

      if (i === 0) {
        p.style.marginTop = '0';
      }

      text.node.appendChild(p);
    });
    text.node.style.maxWidth = '500px';

    const body = super.createBody(value);
    body.removeClass('jp-Dialog-body');

    layout.addWidget(text);
    layout.addWidget(body);

    wrapper.addClass('jp-Dialog-body');
    return wrapper;
  }

  createFooter(
    buttons: ReadonlyArray<HTMLElement>,
    checkbox: HTMLElement | null
  ): Widget {
    return super.createFooter(
      buttons.map(button => {
        if (button.className.includes('jp-mod-accept')) {
          // Style the button as a warning button
          button.className += ' jp-mod-warn';
          // Initially disable the button, it will be enabled when the user
          // types "affirm" in the input field.
          button.setAttribute('disabled', '');
        }
        return button;
      }),
      checkbox
    );
  }
}

const plugins = [
  filebrowserDownloadPlugin,
  filebrowserOpenBrowserTabPlugin,
  docmanagerDownloadPlugin,
  docmanagerOpenBrowserTabPlugin,
  notebookExportPlugin,
  uploadInterceptPlugin
];
export default plugins;
