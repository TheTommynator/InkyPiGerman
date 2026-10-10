// Function to Show the Response Modal
function showResponseModal(status, message) {
    const modal = document.getElementById('responseModal');
    const modalContent = document.getElementById('modalContent');
    const modalMessage = document.getElementById('modalMessage');

    // Remove any previous status classes
    modal.classList.remove('success', 'failure');

    // Add the correct class based on the status
    if (status === 'success') {
        modal.classList.add('success'); // Apply success class
    } else {
        modal.classList.add('failure'); // Apply failure class
    }
    modalMessage.textContent = message;

    // Display Modal
    modal.style.display = 'block';

    // Auto-Close Modal After 10 Seconds
    setTimeout(() => closeResponseModal(), 10000);
}

// Function to Close the Modal
function closeResponseModal() {
    const modal = document.getElementById('responseModal');
    modal.style.display = 'none';
}

// Kurze Bestätigung unten („Gesichert“), verschwindet von selbst
let toastTimer = null;
function showToast(message, isError) {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.toggle('toast-error', !!isError);
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, isError ? 5000 : 1800);
}

// Speichert einen Teil der Einstellungen sofort (JSON) und meldet das Ergebnis kurz unten
async function saveNow(url, data) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Speichern fehlgeschlagen');
        showToast('Gesichert');
        return true;
    } catch (e) {
        showToast(e.message, true);
        return false;
    }
}
