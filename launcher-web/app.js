const API = "http://localhost:8081/api";

const elements = {
    badge: document.getElementById('status-badge'),
    statusText: document.getElementById('status-text'),
    btnStart: document.getElementById('btn-start'),
    btnStop: document.getElementById('btn-stop'),
    btnOpen: document.getElementById('btn-open'),
    btnClear: document.getElementById('btn-clear-logs'),
    logOutput: document.getElementById('log-output')
};

let isRunning = false;
let isWorking = false; // true when starting or stopping

// --- Polling ---
async function checkStatus() {
    if (isWorking) return; // Don't override status while btn action is pending
    
    try {
        const res = await fetch(`${API}/status`);
        if (res.ok) {
            const data = await res.json();
            setRunning(data.running);
            
            // Fetch any new logs
            if (data.logs && data.logs.length > 0) {
                data.logs.forEach(msg => logMsg(msg, 'info'));
            }
        } else {
            setRunning(false);
        }
    } catch (e) {
        setRunning(false);
    }
}

// Check immediately, then every 2 seconds
checkStatus();
setInterval(checkStatus, 2000);

// --- State Management ---
function setRunning(running) {
    isRunning = running;
    isWorking = false;

    if (running) {
        elements.badge.className = 'status-badge running';
        elements.statusText.textContent = 'App Running';
        elements.statusText.style.color = 'var(--succ)';
        
        elements.btnStart.disabled = true;
        elements.btnStop.disabled = false;
        elements.btnOpen.disabled = false;
    } else {
        elements.badge.className = 'status-badge stopped';
        elements.statusText.textContent = 'App Stopped';
        elements.statusText.style.color = 'var(--text-sec)';
        
        elements.btnStart.disabled = false;
        elements.btnStop.disabled = true;
        elements.btnOpen.disabled = true;
    }
}

function setWorking(label) {
    isWorking = true;
    elements.badge.className = 'status-badge working';
    elements.statusText.textContent = label + '...';
    elements.statusText.style.color = 'var(--warn)';

    elements.btnStart.disabled = true;
    elements.btnStop.disabled = true;
    elements.btnOpen.disabled = true;
}

// --- Action Handlers ---
elements.btnStart.addEventListener('click', async () => {
    setWorking('Starting App');
    logMsg('Sending start command to server...', 'info');
    
    try {
        const res = await fetch(`${API}/start`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start');
        logMsg('Dependencies checked, server launching...', 'success');
        
        // Wait a bit for Uvicorn to boot
        setTimeout(() => {
            isWorking = false;
            checkStatus();
        }, 2000);
    } catch (e) {
        logMsg(`Error: ${e.message}`, 'error');
        setRunning(false);
    }
});

elements.btnStop.addEventListener('click', async () => {
    setWorking('Stopping App');
    logMsg('Sending stop command...', 'info');
    
    try {
        const res = await fetch(`${API}/stop`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to stop');
        logMsg('Server process killed.', 'success');
        
        setTimeout(() => {
            isWorking = false;
            checkStatus();
        }, 1000);
    } catch (e) {
        logMsg(`Error: ${e.message}`, 'error');
        isWorking = false;
        checkStatus();
    }
});

elements.btnOpen.addEventListener('click', () => {
    window.open('http://localhost:8000', '_blank');
});

elements.btnClear.addEventListener('click', () => {
    elements.logOutput.innerHTML = '';
});

// --- Logging ---
function logMsg(msg, level = 'info') {
    const el = document.createElement('div');
    el.className = `log-entry ${level}`;
    
    // Add timestamp
    const now = new Date();
    const ts = now.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    
    el.innerHTML = `<span style="opacity:0.5; margin-right:8px;">[${ts}]</span> ${msg}`;
    
    elements.logOutput.appendChild(el);
    elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

logMsg('Launcher UI loaded. Waiting for backend status...', 'info');
