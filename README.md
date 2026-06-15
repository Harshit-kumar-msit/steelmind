# SteelMind
https://steelmind-frontend-ten.vercel.app
## Intelligent Maintenance Decision Support System for Steel Manufacturing

SteelMind is an AI-powered maintenance copilot designed to assist maintenance engineers in diagnosing equipment failures, identifying probable root causes, prioritizing interventions, and supporting proactive maintenance planning within steel manufacturing environments.

The platform consolidates operational logs, maintenance knowledge, equipment documentation, condition monitoring insights, and conversational intelligence into a unified decision-support experience.

---

## Problem Statement

Steel manufacturing facilities operate highly interconnected and capital-intensive equipment. Unplanned downtime can lead to significant production losses, increased maintenance costs, operational inefficiencies, and safety risks.

Maintenance teams often rely on fragmented information sources such as:

* Equipment manuals
* Standard Operating Procedures (SOPs)
* Historical maintenance records
* Failure analysis reports
* Alarm and delay logs
* Condition monitoring data

SteelMind addresses this challenge by providing a context-aware maintenance assistant capable of transforming scattered information into actionable maintenance intelligence.

---

## Key Capabilities

### Conversational Maintenance Copilot

* Natural language troubleshooting assistance
* Context-aware multi-turn conversations
* Guided root cause investigation
* Explainable recommendations with source citations

### Knowledge-Driven Reasoning

* Retrieval-Augmented Generation (RAG)
* Equipment manual understanding
* SOP-based recommendations
* Historical failure pattern retrieval
* Equipment-specific contextual responses

### Equipment Health Monitoring

* Plant-wide health visibility
* Anomaly identification
* Degradation trend analysis
* Early warning generation
* Critical asset monitoring

### Maintenance Decision Support

* Probable fault diagnosis
* Root cause analysis
* Remaining Useful Life (RUL) estimation
* Risk-based prioritization
* Maintenance action recommendations

### Planning and Reporting

* Work order generation
* Spare availability verification
* Procurement-aware recommendations
* Automated maintenance summaries
* Alert and incident reporting

---

## Technology Stack

| Layer                | Technologies                    |
| -------------------- | ------------------------------- |
| Frontend             | React, TypeScript, Tailwind CSS |
| Backend              | FastAPI, Python                 |
| LLM Layer            | Groq API, Llama 3.3 70B         |
| Knowledge Layer      | ChromaDB, Embedding Models      |
| Operational Database | PostgreSQL                      |
| Time-Series Storage  | InfluxDB                        |
| Background Services  | Redis                           |
| Machine Learning     | Scikit-learn                    |
| Containerization     | Docker, Docker Compose          |

---

## System Architecture

SteelMind combines conversational intelligence, retrieval-based reasoning, condition monitoring analytics, and maintenance decision support.

```text
Maintenance Engineer
        │
        ▼
 Conversational Copilot
        │
        ▼
  LLM Orchestrator
        │
 ┌──────┼─────────────┐
 │      │             │
 ▼      ▼             ▼
RAG   Analytics   Decision Engine
 │      │             │
 ▼      ▼             ▼
Knowledge  Health   Prioritization
 Base      Insights Recommendations
        │
        ▼
 Reports • Alerts • Work Orders
```

---

## Features

### AI Copilot

* Streaming conversational responses
* Context retention across interactions
* Equipment-specific assistance
* Actionable maintenance guidance

### Retrieval-Augmented Generation

* PDF ingestion
* DOCX ingestion
* Text document ingestion
* Semantic retrieval
* Citation support

### Predictive Insights

* Isolation Forest anomaly detection
* Sensor-level anomaly contributions
* Trend-based Remaining Useful Life estimation
* Priority scoring framework

### Operational Workflows

* Alert acknowledgement
* Alert resolution
* Work order lifecycle management
* Maintenance planning support

---

## Quick Start

### Prerequisites

Ensure the following tools are installed:

* Docker
* Docker Compose
* Groq API Key

Optional for local development:

* Python 3.11+
* Node.js 20+

---

## Environment Configuration

Copy the environment template:

```bash
cp .env.example .env
```

Update the required variables:

```env
GROQ_API_KEY=your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_FAST_MODEL=llama-3.1-8b-instant
```

---

## Running with Docker

Start supporting services:

```bash
docker-compose up -d postgres influxdb redis
```

Start the backend:

```bash
docker-compose up backend
```

Start the frontend:

```bash
docker-compose up frontend
```

### First Startup

During initialization, SteelMind automatically:

* Generates synthetic industrial datasets
* Creates equipment records
* Simulates 30 days of sensor history
* Seeds maintenance logs
* Generates work orders
* Populates the knowledge repository
* Trains anomaly detection models

The initialization process may take approximately 2–3 minutes.

---

## Accessing the Platform

| Service            | URL                        |
| ------------------ | -------------------------- |
| Dashboard          | http://localhost:3000      |
| API Documentation  | http://localhost:8000/docs |
| InfluxDB Interface | http://localhost:8086      |

### Demonstration Credentials

Email:

```text
engineer@steelmind.demo
```

Password:

```text
demo1234
```

---

## Local Development

### Backend

```bash
cd backend

python -m venv venv

source venv/bin/activate
# Windows:
# venv\Scripts\activate

pip install -r requirements.txt
```

Start infrastructure services:

```bash
docker-compose up -d postgres influxdb redis
```

Configure environment:

```bash
cp ../.env.example .env
```

Run the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

---

### Frontend

```bash
cd frontend

npm install

npm run dev
```

Frontend will be available at:

```text
http://localhost:3000
```

---

## Project Structure

```text
steelmind/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes/
│   │   ├── ai/
│   │   │   ├── rag/
│   │   │   ├── anomaly/
│   │   │   ├── prediction/
│   │   │   ├── decision/
│   │   │   └── llm/
│   │   ├── db/
│   │   └── services/
│   ├── data/
│   │   ├── synthetic/
│   │   ├── raw_docs/
│   │   └── chroma_db/
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── api/
│       ├── store/
│       └── types/
│
├── docker-compose.yml
└── README.md
```

---

## API Overview

| Method | Endpoint                                | Description          |
| ------ | --------------------------------------- | -------------------- |
| GET    | `/api/v1/equipment`                     | List equipment       |
| GET    | `/api/v1/equipment/summary`             | Plant health metrics |
| GET    | `/api/v1/equipment/{id}`                | Equipment details    |
| POST   | `/api/v1/equipment/{id}/refresh-health` | Refresh health state |
| GET    | `/api/v1/sensors/{id}/history`          | Sensor history       |
| GET    | `/api/v1/sensors/{id}/snapshot`         | Latest readings      |
| GET    | `/api/v1/anomaly/{id}/score`            | Anomaly score        |
| GET    | `/api/v1/alerts`                        | List alerts          |
| PATCH  | `/api/v1/alerts/{code}/acknowledge`     | Acknowledge alert    |
| GET    | `/api/v1/workorders`                    | List work orders     |
| POST   | `/api/v1/workorders`                    | Create work order    |
| GET    | `/api/v1/copilot/chat/stream`           | Streaming chat       |
| WS     | `/api/v1/copilot/ws/{session_id}`       | WebSocket chat       |
| GET    | `/api/v1/inventory`                     | Spare inventory      |
| GET    | `/api/v1/inventory/check`               | Availability check   |
| POST   | `/api/v1/reports/weekly-summary`        | Generate report      |

---

## Design Rationale

### Why Groq and Llama 3.3 70B?

* Fast inference with streaming responses
* Strong reasoning capabilities
* Suitable for technical assistance scenarios
* Efficient for hackathon-scale deployments

### Why Retrieval-Augmented Generation?

* Reduces hallucinations
* Grounds responses in supporting documents
* Provides explainability through citations
* Enables equipment-specific assistance

### Why Isolation Forest?

* Minimal requirement for labeled data
* Lightweight CPU-based training
* Suitable for synthetic and real industrial datasets
* Provides interpretable anomaly scores

### Why ChromaDB?

* Embedded deployment
* Persistent storage
* Metadata filtering support
* Easy migration path to production vector databases

### Why InfluxDB?

* Optimized for time-series workloads
* Efficient sensor storage
* Flexible aggregation capabilities
* Retention policy support

---

## Suggested Evaluation Workflow

1. Open the dashboard and review plant-wide equipment health.
2. Identify critical assets and active alerts.
3. Select an equipment item for investigation.
4. Ask the Copilot about observed abnormalities.
5. Review retrieved evidence and recommended actions.
6. Generate a maintenance work order.
7. Verify spare availability.
8. Explore degradation trends and anomaly explanations.
9. Generate a maintenance summary report.
10. Acknowledge and resolve alerts.

---

## Future Enhancements

Potential extensions beyond the prototype include:

* OPC-UA integration with SCADA systems
* MQTT support for live equipment telemetry
* SAP PM and IBM Maximo integration
* LDAP and Active Directory authentication
* Advanced alert routing
* Scheduled model retraining
* Multi-plant deployment support
* Role-based recommendation policies

---

## Assumptions and Limitations

* Synthetic datasets are used for demonstration purposes.
* RUL estimation is trend-based and not trained on real failure histories.
* Recommendations are intended as decision support and not autonomous execution.
* Production deployments require integration with plant systems and validation using real operational data.

---

## Prototype Scope

SteelMind demonstrates how conversational AI, retrieval-based reasoning, and maintenance analytics can be unified into a practical decision-support system for industrial operations.

The prototype is designed to showcase the transition from reactive troubleshooting toward proactive and informed maintenance practices in steel manufacturing environments.

---

## Team

Developed as a prototype for an Industrial AI Maintenance Challenge focused on improving maintenance effectiveness, reducing downtime, and enabling intelligent decision support in steel manufacturing.
