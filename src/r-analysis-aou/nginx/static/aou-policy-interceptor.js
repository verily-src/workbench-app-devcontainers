(function() {
    'use strict';

    // ============================================
    // Configuration
    // ============================================

    const POLICY_CONFIG = {
        uploadTitle: 'Policy Reminder',
        uploadMessage: 'The All of Us Data Use Policies prohibit you from uploading data or files containing personally identifiable information (PII). Any external data, files, or software that is uploaded into the Workspace should be exclusively for the research purpose that was provided for this Workspace.',
        downloadTitle: 'Policy Reminder',
        downloadMessage: [
            'The All of Us Data Use Policies prohibit you from removing participant-level data from the workbench. You are also prohibited from publishing or otherwise distributing any data or aggregate statistics corresponding to fewer than 20 participants unless expressly permitted by our data use policies.',
            'To continue, affirm that this download will be used in accordance with the All of Us data use policy by typing "affirm" below.'
        ],
        affirmText: 'affirm'
    };

    // ============================================
    // Modal Dialog Management
    // ============================================

    function createModal(type, callback) {
        // Remove any existing modals
        const existing = document.getElementById('aou-policy-modal');
        if (existing) {
            existing.remove();
        }

        const modal = document.createElement('div');
        modal.id = 'aou-policy-modal';
        modal.className = 'aou-modal-overlay';

        const content = document.createElement('div');
        content.className = 'aou-modal-content';

        if (type === 'upload') {
            content.innerHTML = createUploadModalHTML();
            attachUploadHandlers(modal, content, callback);
        } else if (type === 'download') {
            content.innerHTML = createDownloadModalHTML();
            attachDownloadHandlers(modal, content, callback);
        }

        modal.appendChild(content);
        document.body.appendChild(modal);

        // Focus management
        setTimeout(() => {
            const input = content.querySelector('input[type="text"]');
            if (input) input.focus();
        }, 100);

        return modal;
    }

    function createUploadModalHTML() {
        return `
            <div class="aou-modal-header">
                <h2>${POLICY_CONFIG.uploadTitle}</h2>
            </div>
            <div class="aou-modal-body">
                <p>${POLICY_CONFIG.uploadMessage}</p>
            </div>
            <div class="aou-modal-footer">
                <button class="aou-button aou-button-secondary" data-action="cancel">Cancel</button>
                <button class="aou-button aou-button-warning" data-action="continue">Continue</button>
            </div>
        `;
    }

    function createDownloadModalHTML() {
        return `
            <div class="aou-modal-header">
                <h2>${POLICY_CONFIG.downloadTitle}</h2>
            </div>
            <div class="aou-modal-body">
                ${POLICY_CONFIG.downloadMessage.map(msg => `<p>${msg}</p>`).join('')}
                <div class="aou-input-group">
                    <input type="text"
                           id="aou-affirm-input"
                           placeholder="Type 'affirm' to continue"
                           autocomplete="off"
                           spellcheck="false">
                </div>
                <div id="aou-error-message" class="aou-error-message" style="display: none;">
                    You must type "affirm" to continue.
                </div>
            </div>
            <div class="aou-modal-footer">
                <button class="aou-button aou-button-secondary" data-action="cancel">Cancel</button>
                <button class="aou-button aou-button-warning" data-action="continue" disabled>Continue</button>
            </div>
        `;
    }

    function attachUploadHandlers(modal, content, callback) {
        content.querySelector('[data-action="cancel"]').onclick = () => {
            modal.remove();
            callback(false);
        };
        content.querySelector('[data-action="continue"]').onclick = () => {
            modal.remove();
            callback(true);
        };
        modal.onclick = (e) => {
            if (e.target === modal) {
                modal.remove();
                callback(false);
            }
        };
    }

    function attachDownloadHandlers(modal, content, callback) {
        const input = content.querySelector('#aou-affirm-input');
        const continueBtn = content.querySelector('[data-action="continue"]');
        const errorMsg = content.querySelector('#aou-error-message');

        input.oninput = () => {
            const isValid = input.value.toLowerCase() === POLICY_CONFIG.affirmText;
            continueBtn.disabled = !isValid;
            errorMsg.style.display = 'none';
        };

        input.onkeydown = (e) => {
            if (e.key === 'Enter' && !continueBtn.disabled) {
                continueBtn.click();
            }
        };

        continueBtn.onclick = () => {
            if (input.value.toLowerCase() === POLICY_CONFIG.affirmText) {
                modal.remove();
                callback(true);
            } else {
                errorMsg.style.display = 'block';
            }
        };

        content.querySelector('[data-action="cancel"]').onclick = () => {
            modal.remove();
            callback(false);
        };

        modal.onclick = (e) => {
            if (e.target === modal) {
                modal.remove();
                callback(false);
            }
        };
    }

    function withinRstudioModal(target) {
        const modal = document.querySelector('.rstudio_modal_dialog');
        return modal && modal.contains(target);
    }

    // ============================================
    // Download Interception
    // ============================================

    function interceptDownloads() {
        // Intercept clicks on download buttons/links
        document.addEventListener('click', function(e) {
            const target = e.target.closest('button');
            if (!target) return;

            // Check if this is a download button
            const isDownload = e.target.textContent.toLowerCase().includes('download')

            if (!(isDownload && withinRstudioModal(target))) return;

            // Skip if already affirmed
            if (e.target.dataset.aouAffirmed === 'true') {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            if (e.target.dataset.aouModalOpen === 'true') {
                const existing = document.getElementById('aou-policy-modal');
                if (existing) {
                    existing.querySelector('[data-action="continue"]').click();
                }
                return;
            }

            // Show download policy modal
            e.target.dataset.aouModalOpen = 'true';
            createModal('download', (affirmed) => {
                delete e.target.dataset.aouModalOpen;
                if (affirmed) {
                    // Mark as affirmed and trigger the action
                    e.target.dataset.aouAffirmed = 'true';
                    setTimeout(() => {
                        e.target.click();
                    }, 0);

                    // Reset affirmation flag after action
                    setTimeout(() => {
                        delete e.target.dataset.aouAffirmed;
                    }, 100);
                }
            });
        }, true);
    }

    // ============================================
    // Upload Interception
    // ============================================

    function interceptUploads() {
        // Monitor file input changes
        document.addEventListener('change', function(e) {
            if (e.target.type !== 'file') return;
            if (!withinRstudioModal(e.target)) return;

            const files = e.target.files;
            if (!files || files.length === 0) return;

            // Show upload policy modal
            createModal('upload', (affirmed) => {
                if (!affirmed) {
                    // Clear the file input
                    e.target.value = '';
                }
            });
        }, true);
    }

    // ============================================
    // Initialization
    // ============================================

    function init() {
        // Wait for RStudio to fully load
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                interceptDownloads();
                interceptUploads();
            });
        } else {
            interceptDownloads();
            interceptUploads();
        }
    }

    init();
})();
