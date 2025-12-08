#!/bin/bash
echo "🔧 Установка Python и зависимостей..."
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git -y

git clone https://github.com/Choodaev/avatar-bot.git
cd avatar-bot

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Готово! Теперь:"
echo "1. nano .env"
echo "2. sudo cp avatar-bot.service /etc/systemd/system/"
echo "3. sudo systemctl enable avatar-bot"
echo "4. sudo systemctl start avatar-bot"
