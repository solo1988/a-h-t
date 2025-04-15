# 🏆 Achievement Tracker

**Achievement Tracker** — это веб-приложение для отслеживания и мониторинга игровых достижений в реальном времени.  
Приложение интегрируется с API Steam и локальным источником (`Achievement Watcher`), ведёт базу данных достижений и отправляет push-уведомления при их получении.

## 🚀 Возможности

- Подключение к `Achievement Watcher` через WebSocket
- Интеграция с Steam API
- Хранение информации об играх и достижениях в SQLite
- Отображение данных через веб-интерфейс
- Push-уведомления в PWA при получении достижений
- PWA с offline-режимом и кастомным Service Worker

## 🛠️ Установка

> ⚠ Требуется Python 3.10+ и установленный `git`.

```bash
git clone https://github.com/solo1988/a-h-t.git
cd a-h-t
python -m venv venv
source venv/bin/activate     # Linux/macOS
venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn main:app --reload

## ⚙️ Автозапуск через systemd (Linux)

Чтобы приложение запускалось автоматически как служба:

1. Создайте unit-файл systemd:

```bash
sudo nano /etc/systemd/system/achievement-tracker.service
```

2. Вставьте в него:

```bash
[Unit]
Description=Achievement Tracker Web App
After=network.target

[Service]
User=USERNAME
WorkingDirectory=/путь/к/a-h-t
ExecStart=/путь/к/a-h-t/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

> ⚠ Замените `USERNAME` и пути на свои (используйте `whoami` и `pwd` для подстановки).

3. Перезапустите systemd и включите автозапуск:

```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable achievement-tracker
sudo systemctl start achievement-tracker
```

4. Проверить статус:

```bash
sudo systemctl status achievement-tracker
```

Теперь приложение автоматически стартует при загрузке системы и доступно по http://<ip>:8000.

