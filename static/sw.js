self.addEventListener("install", (event) => {
    console.log("Service Worker установлен");
    event.waitUntil(
        caches.open("app-cache").then((cache) => {
            return cache.addAll([
                "/",
                "/static/manifest.json",
                "/static/icon-192x192.png", // иконки из манифеста
                "/static/icon-512x512.png"
            ]);
        })
    );
    self.skipWaiting();  // Принудительная активация
});

self.addEventListener('activate', function(event) {
    console.log('Service Worker успешно активирован!!!');
});

self.addEventListener("fetch", (event) => {
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});

self.addEventListener('push', function(event) {
    console.log('Push-сообщение получено:', event);

    const data = event.data ? event.data.json() : {};
    const title = data.title || 'Новое достижение';
    const options = {
        body: data.body || 'Вы получили новое достижение!',
        icon: data.icon || '/static/images/achievement-icon.png',
        data: {
  url: data.url || 'https://achievs.fayya.keenetic.link'
}

    };

    event.waitUntil(
        self.registration.showNotification(title, options)
            .then(() => {
                console.log("Push уведомление показано");
            })
            .catch((error) => {
                console.error("Ошибка при показе уведомления:", error);
            })
    );
});

self.addEventListener("notificationclick", function(event) {
    event.notification.close();

    const targetUrl = event.notification.data?.url || "/";

    event.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then(windowClients => {
            for (let client of windowClients) {
                if (client.url === targetUrl && "focus" in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

