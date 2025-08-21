const VAPID_PUBLIC_KEY = "BPbVTP_DQbdgTrMuOi4GW6eQ8F5vVezzxsAYQZs1_cjTEF079H3EqgeOvhiSD7ZxgBzS5EoFT2nRrGX5Z3AOZ2I";  // Замените на свой публичный ключ

document.addEventListener("DOMContentLoaded", function () {
    if ("serviceWorker" in navigator) {
        const version = Date.now();  // 👈 добавляем метку времени
        navigator.serviceWorker.register(`/static/sw.js?v=${version}`)
            .then((reg) => {
                console.log("Service Worker зарегистрирован из фронта!", reg);
                reg.update();  // Принудительно обновляем воркер
                initPushSubscription(reg);
                // unsubscribePush(reg);
            })
            .catch((err) => {
                console.error("Ошибка регистрации Service Worker:", err);
            });
    }
});

async function unsubscribePush(registration) {
    try {
        const subscription = await registration.pushManager.getSubscription();

        if (subscription) {
            console.log("Удаляем подписку с endpoint:", subscription.endpoint);

            const successful = await subscription.unsubscribe();
        } else {
            console.log("Подписка не найдена");
        }
    } catch (error) {
        console.error("Ошибка при удалении подписки:", error);
    }
}


async function initPushSubscription(registration) {
    console.log("Пробуем подписку");

    if (!("Notification" in window)) {
        console.log("Уведомления не поддерживаются");
        return;
    }

    const permission = await Notification.requestPermission();
    console.log("Разрешение на уведомления:", permission);
    if (permission !== "granted") {
        console.log("Пользователь не разрешил уведомления");
        return;
    }

    try {
        const existingSubscription = await registration.pushManager.getSubscription();
        console.log("Проверка существующей подписки", existingSubscription);

        if (!existingSubscription) {
            console.log("Создаем новую подписку...");
            const newSubscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlB64ToUint8Array(VAPID_PUBLIC_KEY)
            });

            const rawKeys = newSubscription.toJSON().keys;
            const payload = {
                endpoint: newSubscription.endpoint,
                p256dh: rawKeys.p256dh,
                auth: rawKeys.auth
            };

            console.log("Отправляем подписку на сервер:", payload);
            await sendSubscriptionToServer(payload);

        } else {
            console.log("Уже есть подписка", existingSubscription);

            // 🔍 Проверяем наличие подписки в базе
            const checkResp = await fetch("/check_subscription", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({endpoint: existingSubscription.endpoint})
            });

            const checkResult = await checkResp.json();
            if (!checkResp.ok || !checkResult.exists) {
                console.warn("Подписка не найдена на сервере, удаляем...");

                await unsubscribePush(registration);
                location.reload();  // 🔄 перезагрузка страницы
            } else {
                console.log("Подписка в базе подтверждена");
            }
        }
    } catch (err) {
        console.error("Ошибка подписки:", err);
    }
}


async function sendSubscriptionToServer(subscription) {
    const response = await fetch('/subscribe', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(subscription)
    });

    if (response.ok) {
        console.log("Подписка отправлена на сервер");
    } else {
        console.error("Ошибка при отправке подписки на сервер", await response.text());
    }
}

function urlB64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    return new Uint8Array([...rawData].map(char => char.charCodeAt(0)));
}