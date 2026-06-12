/**
 * Cricket Annotation Tool - Frontend Logic
 * Handles bounding box annotation using Fabric.js
 */

let canvas;
let currentTask = null;
let selectedLabel = null;
let annotations = [];
let isDrawing = false;
let currentRect = null;

// Label colors
const labelColors = {
    'Batting': '#FF6B6B',
    'Bowling': '#4ECDC4',
    'Fielding': '#95E1D3',
    'Wicketkeeping': '#FFE66D',
    'Ball': '#00FF00'
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initCanvas();
    loadStats();
    setupEventListeners();
});

function initCanvas() {
    canvas = new fabric.Canvas('annotation-canvas', {
        width: 800,
        height: 600,
        backgroundColor: '#f0f0f0'
    });

    // Mouse down - start drawing
    canvas.on('mouse:down', function(options) {
        if (!selectedLabel) {
            alert('Please select a label first');
            return;
        }

        isDrawing = true;
        const pointer = canvas.getPointer(options.e);

        currentRect = new fabric.Rect({
            left: pointer.x,
            top: pointer.y,
            width: 0,
            height: 0,
            fill: 'transparent',
            stroke: labelColors[selectedLabel],
            strokeWidth: 3,
            selectable: true,
            hasControls: true
        });

        canvas.add(currentRect);
    });

    // Mouse move - update rectangle size
    canvas.on('mouse:move', function(options) {
        if (!isDrawing) return;

        const pointer = canvas.getPointer(options.e);
        const width = pointer.x - currentRect.left;
        const height = pointer.y - currentRect.top;

        currentRect.set({
            width: width,
            height: height
        });

        canvas.renderAll();
    });

    // Mouse up - finish drawing
    canvas.on('mouse:up', function() {
        if (!isDrawing) return;

        isDrawing = false;

        // Store annotation
        annotations.push({
            label: selectedLabel,
            x: currentRect.left / canvas.width * 100,
            y: currentRect.top / canvas.height * 100,
            width: currentRect.width / canvas.width * 100,
            height: currentRect.height / canvas.height * 100,
            fabric_obj: currentRect
        });

        // Add label text
        const text = new fabric.Text(selectedLabel, {
            left: currentRect.left,
            top: currentRect.top - 20,
            fontSize: 16,
            fill: labelColors[selectedLabel],
            fontWeight: 'bold',
            selectable: false
        });

        canvas.add(text);
        updateAnnotationsList();

        currentRect = null;
    });
}

function setupEventListeners() {
    // Load tasks button
    document.getElementById('load-tasks-btn').addEventListener('click', loadTasks);

    // Label buttons
    document.querySelectorAll('.label-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            // Remove active class from all
            document.querySelectorAll('.label-btn').forEach(b => b.classList.remove('active'));

            // Add active class to clicked
            this.classList.add('active');
            selectedLabel = this.dataset.label;
        });
    });

    // Undo button
    document.getElementById('undo-btn').addEventListener('click', undo);

    // Clear button
    document.getElementById('clear-btn').addEventListener('click', clearAll);

    // Submit button
    document.getElementById('submit-btn').addEventListener('click', submitAnnotation);

    // Skip button
    document.getElementById('skip-btn').addEventListener('click', skipTask);

    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // 1-5 for label selection
        if (e.key >= '1' && e.key <= '5') {
            const btns = document.querySelectorAll('.label-btn');
            const index = parseInt(e.key) - 1;
            if (btns[index]) {
                btns[index].click();
            }
        }

        // Z for undo
        if (e.key === 'z' || e.key === 'Z') {
            undo();
        }

        // Enter to submit
        if (e.key === 'Enter' && currentTask) {
            submitAnnotation();
        }
    });
}

async function loadTasks() {
    try {
        const response = await fetch('/api/tasks?limit=10&status=pending');
        const data = await response.json();

        const container = document.getElementById('tasks-container');
        container.innerHTML = '';

        if (data.tasks.length === 0) {
            container.innerHTML = '<p class="message">No pending tasks</p>';
            return;
        }

        data.tasks.forEach(task => {
            const taskDiv = document.createElement('div');
            taskDiv.className = 'task-item';
            taskDiv.innerHTML = `
                <strong>${task.task_id.substring(0, 8)}...</strong>
                <span>${task.task_type}</span>
            `;
            taskDiv.onclick = () => loadTask(task);
            container.appendChild(taskDiv);
        });

    } catch (error) {
        console.error('Error loading tasks:', error);
        alert('Failed to load tasks');
    }
}

async function loadTask(task) {
    currentTask = task;

    // Mark as in_progress
    await fetch(`/api/tasks/${task.task_id}/start`, { method: 'POST' });

    // Show annotation area
    document.getElementById('no-task-message').style.display = 'none';
    document.getElementById('annotation-area').style.display = 'block';
    document.getElementById('current-task-id').textContent = `Task: ${task.task_id}`;

    // Clear previous annotations
    clearAll();

    // Load image
    fabric.Image.fromURL(task.image_url, function(img) {
        // Scale image to fit canvas
        const scale = Math.min(
            canvas.width / img.width,
            canvas.height / img.height
        );

        img.scale(scale);
        img.set({
            left: 0,
            top: 0,
            selectable: false
        });

        canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
    }, { crossOrigin: 'anonymous' });

    // Update stats
    loadStats();
}

function undo() {
    if (annotations.length === 0) return;

    const lastAnnotation = annotations.pop();
    canvas.remove(lastAnnotation.fabric_obj);

    // Remove associated text
    const objects = canvas.getObjects();
    const lastText = objects[objects.length - 1];
    if (lastText.type === 'text') {
        canvas.remove(lastText);
    }

    canvas.renderAll();
    updateAnnotationsList();
}

function clearAll() {
    annotations = [];
    canvas.clear();
    canvas.backgroundColor = '#f0f0f0';

    // Reload background image if exists
    if (currentTask) {
        fabric.Image.fromURL(currentTask.image_url, function(img) {
            const scale = Math.min(
                canvas.width / img.width,
                canvas.height / img.height
            );
            img.scale(scale);
            img.set({ left: 0, top: 0, selectable: false });
            canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
        }, { crossOrigin: 'anonymous' });
    }

    updateAnnotationsList();
}

function updateAnnotationsList() {
    const container = document.getElementById('annotations-container');

    if (annotations.length === 0) {
        container.innerHTML = '<p class="message">No annotations yet</p>';
        return;
    }

    container.innerHTML = annotations.map((ann, idx) => `
        <div class="annotation-item" style="border-left: 4px solid ${labelColors[ann.label]};">
            <strong>${idx + 1}. ${ann.label}</strong>
            <small>x:${ann.x.toFixed(1)}% y:${ann.y.toFixed(1)}%</small>
        </div>
    `).join('');
}

async function submitAnnotation() {
    if (!currentTask) {
        alert('No task selected');
        return;
    }

    if (annotations.length === 0) {
        if (!confirm('No annotations added. Submit empty?')) {
            return;
        }
    }

    const annotationData = {
        task_id: currentTask.task_id,
        annotator: 'current_user',  // TODO: Get from auth
        annotation_type: 'bbox',
        annotation_data: {
            bboxes: annotations.map(ann => ({
                label: ann.label,
                x: ann.x,
                y: ann.y,
                width: ann.width,
                height: ann.height
            }))
        }
    };

    try {
        const response = await fetch('/api/annotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(annotationData)
        });

        const result = await response.json();

        if (result.status === 'success') {
            alert('✓ Annotation saved!');

            // Clear and load next task
            currentTask = null;
            document.getElementById('annotation-area').style.display = 'none';
            document.getElementById('no-task-message').style.display = 'block';

            loadTasks();
            loadStats();
        } else {
            alert('Error saving annotation: ' + JSON.stringify(result.errors));
        }

    } catch (error) {
        console.error('Error submitting annotation:', error);
        alert('Failed to submit annotation');
    }
}

function skipTask() {
    if (confirm('Skip this task?')) {
        currentTask = null;
        document.getElementById('annotation-area').style.display = 'none';
        document.getElementById('no-task-message').style.display = 'block';
        clearAll();
        loadTasks();
    }
}

async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();

        document.getElementById('stats-pending').textContent = `Pending: ${stats.pending || 0}`;
        document.getElementById('stats-completed').textContent = `Completed: ${stats.completed || 0}`;
        document.getElementById('stats-total').textContent = `Total: ${stats.total || 0}`;

    } catch (error) {
        console.error('Error loading stats:', error);
    }
}
