# 🌍 Real-Time AI Geo-Food Recommendation System

## 📌 Project Overview

This project is a **Real-Time AI-based Geo-Food Recommendation System** that allows users to query food preferences (e.g., “biryani near me”) and receive intelligent recommendations instantly.

The system uses **WebSockets for real-time communication**, integrates **NLP for query understanding**, and combines **web scraping + API data** to provide contextual results.

---

## 🎯 Objective

* Enable real-time user interaction using WebSockets
* Provide intelligent food recommendations based on user queries
* Combine AI, NLP, and data scraping into a single system
* Build a production-level backend system

---

## 🚀 Key Features

### 🔹 Real-Time Chat System

* Built using **WebSockets (/ws/chat)**
* Supports interactive conversation
* Maintains session-based context

---

### 🔹 AI & NLP Processing

* Understands natural language queries
* Uses:

  * TF-IDF
  * Query parsing
  * Context-aware responses

**Example Queries:**

* “Biryani near me in Pune”
* “Pizza under 200”
* “Best restaurants nearby”

---

### 🔹 Data Integration

* Google Places API
* Web scraping (Zomato, Swiggy)
* Extracts:

  * Restaurant names
  * Distance
  * Price
  * Availability

---

### 🔹 Intelligent Ranking System

* Ranks results based on:

  * Distance
  * Price
  * Relevance
* Returns top recommendations

---

### 🔹 FastAPI Backend

* REST + WebSocket support
* Auto-generated API docs using Swagger

📍 Local API:
http://127.0.0.1:8000/docs

---

## 🛠️ Tech Stack

* **Language:** Python
* **Backend:** FastAPI
* **Real-Time:** WebSockets
* **NLP:** NLTK, TF-IDF
* **ML:** Scikit-learn
* **Web Scraping:** BeautifulSoup, Requests
* **APIs:** Google Places API

---

## 📂 Project Structure

```
Project 2-Rating/
│── api.py              # FastAPI + WebSocket server
│── final.py            # Core logic (GeoFoodSession)
│── nlp_layer.py        # NLP processing
│── Phase_1.py          # Data preprocessing
│── Phase_2.py          # Scraping & API integration
│── test_ws.py          # WebSocket client (input)
│── requirements.txt    # Dependencies
```

---

## ▶️ How to Run Locally

### 1️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 2️⃣ Run Server

```bash
python -m uvicorn api:app --reload
```

---

### 3️⃣ Open API Docs

👉 http://127.0.0.1:8000/docs

---

### 4️⃣ Run WebSocket Client (for input)

```bash
python test_ws.py
```

---

### 5️⃣ Enter Query

```text
You: biryani near me in pune
```

💥 System will return intelligent recommendations

---

## 🧪 Testing & Execution

The system was successfully tested using:

* FastAPI Swagger UI
* WebSocket client interaction

✔ Backend running successfully

✔ WebSocket connection established

✔ Real-time responses generated

---

## 📸 Screenshots

<img width="1860" height="915" alt="Screenshot 2026-04-19 152120" src="https://github.com/user-attachments/assets/d52aa3db-2bc5-4fe6-99f1-f27c5ac349fb" />


**Fig 1:** Swagger UI displaying Geo-Food Assistant API endpoints.

<img width="1807" height="909" alt="Screenshot 2026-04-19 152148" src="https://github.com/user-attachments/assets/b4fab449-c73d-4ad0-91f7-c9187ff3a207" />


**Fig 2:** Successful API response confirming backend is running.

<img width="947" height="433" alt="Screenshot 2026-04-19 153132" src="https://github.com/user-attachments/assets/b0581af5-2e90-40f9-9104-334325bbf954" />


**Fig 3:** Real-time WebSocket response showing AI-based food recommendations.

---

## 🔄 System Workflow

User Query → WebSocket → NLP Processing → Data Fetching → Ranking → Response

---

## ⚠️ Limitations

* Requires internet for API and scraping
* Depends on external data sources
* Performance may vary based on server

---

## 🔐 Security Considerations

* API keys should be secured (not exposed in public repo)
* Proper request validation implemented

---

## 🌍 Deployment

* Deployed on VPS using:

  * Nginx (Reverse Proxy)
  * WebSocket configuration
  * HTTPS enabled

> Note: Live deployment link is currently inactive due to server access limitations.

---

## 🙋‍♀️ Author

**Khushi Kasliwal**

📧 Email: khushikasliwal4@gmail.com

🔗 LinkedIn: https://www.linkedin.com/in/khushi-kasliwal-953692260/

---

## 💬 Let’s Connect!

I’m open to:

* AI & Machine Learning projects
* Backend development opportunities
* Internship collaborations

---

## ⭐ Support

If you found this project useful, consider giving it a ⭐ on GitHub!
