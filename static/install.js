let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); // Предотвращаем автоматическое появление баннера
    deferredPrompt = e;

    const installBtn = document.getElementById("install-btn");
    if (installBtn) {
        installBtn.style.display = "block";

        installBtn.addEventListener("click", () => {
            installBtn.style.display = "none";

            deferredPrompt.prompt();

            deferredPrompt.userChoice.then((choiceResult) => {
                if (choiceResult.outcome === 'accepted') {
                    console.log('✅ Установка подтверждена');
                } else {
                    console.log('❌ Установка отменена');
                }
                deferredPrompt = null;
            });
        });
    }
});
