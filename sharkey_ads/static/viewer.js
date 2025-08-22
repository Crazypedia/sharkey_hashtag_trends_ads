function setupViewer() {
    const viewer = document.getElementById('viewer');
    if (!viewer) return;
    const viewerImg = document.getElementById('viewer-img');
    const viewerText = document.getElementById('viewer-text');
    document.querySelectorAll('.gallery img').forEach(img => {
        img.addEventListener('click', () => {
            viewerImg.src = img.src;
            viewerImg.alt = img.alt;
            viewerText.textContent = img.alt;
            viewer.style.display = 'block';
        });
    });
}

document.addEventListener('DOMContentLoaded', setupViewer);
