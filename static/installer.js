    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault(); // Откладываем показ баннера
        deferredPrompt = e; // Сохраняем событие
        document.getElementById('install-btn').style.display = 'block'; // Показываем кнопку
    });

    document.getElementById('install-btn').addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt(); // Показываем баннер установки
            const choiceResult = await deferredPrompt.userChoice;
            console.log('Результат установки:', choiceResult.outcome);
            deferredPrompt = null; // Сбрасываем
            document.getElementById('install-btn').style.display = 'none';
        }
    });