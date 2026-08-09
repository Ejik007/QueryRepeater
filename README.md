# Leasing Analytics Request Repeater (API Proxy)

Сервис-повторитель запросов к веб-порталу [leasing-analytics.ru/inn/](https://leasing-analytics.ru/inn/) для программного получения договоров лизинга по ИНН юридических и физических лиц.

---

## ⚡ Особенности

- **Высокая скорость**: время выполнения одного запроса **~0.3–0.4 сек.**
- **Чистый REST API**: готовые эндпоинты в формате JSON на базе FastAPI.
- **Интерактивная документация**: автоматические Swagger UI (`/docs`) и ReDoc (`/redoc`).
- **Поддержка CORS**: возможность совершать запросы напрямую из вашего браузерного фронтенда.
- **Контейнеризация**: готов для быстрого деплоя через Docker.

---

## 🚀 Быстрый запуск

### 1. Локальный запуск (через virtualenv)

```bash
# Клонируйте или перейдите в папку проекта
cd /Users/stanislavvoskobojnikov/QueryRepeater

# Создайте виртуальное окружение и установите зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Запустите сервер Uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

После запуска сервер будет доступен по адресу:
- Swagger Документация: `http://localhost:8000/docs`
- Проверка здоровья: `http://localhost:8000/health`

### 2. Запуск через Docker

```bash
# Сборка образа
docker build -t leasing-repeater .

# Запуск контейнера
docker run -d -p 8000:8000 --name leasing-repeater-app leasing-repeater
```

---

## 📡 Описание API Endpoints

### 1. `GET /api/v1/leasing/{inn}`
Возвращает полную информацию по ИНН: сводку по лизинговым компаниям и полный массив договоров.

**Пример запроса**:
```bash
curl -X GET "http://localhost:8000/api/v1/leasing/7707083893"
```

**Пример ответа**:
```json
{
  "inn": "7707083893",
  "total_contracts": 95,
  "summary": [
    {
      "leasing_company": "АО \"ЛИЗИНГОВАЯ КОМПАНИЯ \"КАМАЗ\"",
      "contracts_count": 1
    }
  ],
  "contracts": [
    {
      "contract_number": "1663-ДЛ-23",
      "period_start": "2024-04-25",
      "period_end": "2029-04-30",
      "leasing_company": "Сведения скрыты в соответствии с требованиями постановления Правительства РФ от 12.01.2018 г. №5",
      "category": "Металлообрабатывающее оборудование, комплектующие, инструмент",
      "subject": "0104008 ДРОБИЛЬНО-СОРТИРОВОЧНАЯ УСТАНОВКА (ДСУ-865-23)",
      "url_hash": "B180336D0B20428089C0E6059519602F",
      "brand": "",
      "model": ""
    }
  ]
}
```

---

### 2. `GET /api/v1/leasing/{inn}/contracts`
Возвращает только массив договоров лизинга.

**Пример запроса**:
```bash
curl -X GET "http://localhost:8000/api/v1/leasing/7707083893/contracts"
```

---

### 3. `GET /api/v1/leasing/{inn}/summary`
Возвращает сводку по лизинговым компаниям (количество договоров с каждой ЛК).

**Пример запроса**:
```bash
curl -X GET "http://localhost:8000/api/v1/leasing/7707083893/summary"
```

---

## 💻 Примеры использования в коде

### JavaScript / TypeScript (Fetch API)

```javascript
async function fetchLeasingInfo(inn) {
  try {
    const response = await fetch(`http://localhost:8000/api/v1/leasing/${inn}`);
    if (!response.ok) {
      throw new Error(`Ошибка: ${response.statusText}`);
    }
    const data = await response.json();
    console.log(`Найдено договоров: ${data.total_contracts}`);
    console.log("Договоры:", data.contracts);
  } catch (error) {
    console.error("Ошибка при получении лизинговых данных:", error);
  }
}

// Вызов функции
fetchLeasingInfo("7707083893");
```

### Python (Requests)

```python
import requests

def get_leasing_contracts(inn: str):
    url = f"http://localhost:8000/api/v1/leasing/{inn}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        print(f"ИНН: {data['inn']}, Всего договоров: {data['total_contracts']}")
        for contract in data['contracts']:
            print(f"- Договор {contract['contract_number']} ({contract['period_start']} — {contract['period_end']}): {contract['subject']}")
    else:
        print(f"Ошибка {response.status_code}: {response.json()}")

get_leasing_contracts("7707083893")
```

---

## 🧪 Тестирование

Запустите автоматический набор тестов:

```bash
./venv/bin/python test_api.py
./venv/bin/python test_client.py
```
