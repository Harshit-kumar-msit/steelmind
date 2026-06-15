// src/api/client.ts - Complete API client with logbook + feedback

import axios, { AxiosInstance } from 'axios';
import type {
  Equipment,
  EquipmentDetail,
  PlantSummary,
  Alert,
  WorkOrder,
  SparePart,
  AnomalyScore,
  WeeklyReport,
  SensorReading,
  SensorSnapshot,
  Citation,
  ActionButton,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('steelmind_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('steelmind_token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export const equipmentApi = {
  list: (params?: any) =>
    api.get<Equipment[]>('/equipment', { params }).then(r => r.data),

  summary: () =>
    api.get<PlantSummary>('/equipment/summary').then(r => r.data),

  get: (id: string) =>
    api.get<EquipmentDetail>(`/equipment/${id}`).then(r => r.data),

  refreshHealth: (id: string) =>
    api.post(`/equipment/${id}/refresh-health`).then(r => r.data),
};

export const sensorsApi = {
  history: (id: string, field: string, hours = 24) =>
    api.get<{ records: SensorReading[] }>(
      `/sensors/${id}/history`,
      { params: { field, hours } }
    ).then(r => r.data.records),

  snapshot: (id: string) =>
    api.get<{ snapshot: SensorSnapshot }>(`/sensors/${id}/snapshot`)
      .then(r => r.data.snapshot),

  anomalyChart: (id: string, hours = 72) =>
    api.get<{ anomaly_trend: SensorReading[] }>(
      `/sensors/${id}/anomaly-chart`,
      { params: { hours } }
    ).then(r => r.data.anomaly_trend),
};

export const alertsApi = {
  list: (params?: any) =>
    api.get<Alert[]>('/alerts', { params }).then(r => r.data),

  acknowledge: (code: string, by: string) =>
    api.patch(`/alerts/${code}/acknowledge`, { acknowledged_by: by }).then(r => r.data),

  resolve: (code: string) =>
    api.patch(`/alerts/${code}/resolve`).then(r => r.data),
};

export const workOrdersApi = {
  list: (params?: any) =>
    api.get<WorkOrder[]>('/workorders', { params }).then(r => r.data),

  create: (body: any) =>
    api.post<{ wo_code: string; id: string }>('/workorders', body).then(r => r.data),

  updateStatus: (code: string, status: string) =>
    api.patch(`/workorders/${code}/status`, null, { params: { status } }).then(r => r.data),
};

export const anomalyApi = {
  score: (id: string) =>
    api.get<AnomalyScore>(`/anomaly/${id}/score`).then(r => r.data),
};

export const inventoryApi = {
  list: (params?: any) =>
    api.get<SparePart[]>('/inventory', { params }).then(r => r.data),

  checkParts: (ids: string[]) =>
    api.get('/inventory/check', { params: { part_ids: ids.join(',') } }).then(r => r.data),
};

export const reportsApi = {
  weekly: () =>
    api.post<WeeklyReport>('/reports/weekly-summary').then(r => r.data),
};

export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; user_id: string; role: string; full_name: string }>(
      '/auth/login',
      { email, password }
    ).then(r => r.data),
};

// GAP 1: Logbook API
export interface LogEntry {
  id: string;
  equipment_id: string;
  logged_by: string;
  log_type: string;
  notes: string;
  work_order_id: string;
  created_at: string;
}

export const logbookApi = {
  list: (equipmentId: string, limit = 20) =>
    api.get<LogEntry[]>(
      `/equipment/${equipmentId}/logs`,
      { params: { limit } }
    ).then(r => r.data),

  add: (equipmentId: string, body: {
    logged_by: string;
    log_type: string;
    notes: string;
    work_order_id?: string;
  }) =>
    api.post(`/equipment/${equipmentId}/logs`, body).then(r => r.data),

  context: (equipmentId: string, lastN = 5) =>
    api.get<{ context: string }>(
      `/equipment/${equipmentId}/logs/context`,
      { params: { last_n: lastN } }
    ).then(r => r.data),
};

// GAP 2: Feedback API
export const feedbackApi = {
  submit: (body: {
    session_id: string;
    message_index: number;
    equipment_id: string;
    user_id: string;
    user_query: string;
    ai_response: string;
    rating: number;
    correction_text?: string;
    intent?: string;
  }) =>
    api.post('/copilot/feedback', body).then(r => r.data),

  stats: () =>
    api.get<{ total: number; positive: number; negative: number; helpfulness_rate: number }>(
      '/copilot/feedback/stats'
    ).then(r => r.data),
};

export const chatApi = {
  stream: (
    sessionId: string,
    message: string,
    equipmentId: string,
    userId: string,
    onToken: (t: string) => void,
    onCitations: (c: Citation[]) => void,   // ✅ FIXED (was unknown[])
    onActions: (a: ActionButton[]) => void, // ✅ FIXED (was unknown[])
    onDone: (i: string) => void,
    onError: (e: unknown) => void
  ): EventSource => {

    const params = new URLSearchParams({
      session_id: sessionId,
      message,
      equipment_id: equipmentId,
      user_id: userId
    });

    const es = new EventSource(
      `${BASE_URL}/api/v1/copilot/chat/stream?${params}`
    );

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'token') onToken(data.content);

        if (data.type === 'citations') onCitations(data.data as Citation[]);

        if (data.type === 'actions') onActions(data.data as ActionButton[]);

        if (data.type === 'done') {
          onDone(data.intent);
          es.close();
        }

        if (data.type === 'error') {
          onError(data.message);
          es.close();
        }
      } catch (e) {
        onError(e);
      }
    };

    es.onerror = (e) => {
      onError(e);
      es.close();
    };

    return es;
  },

  getHistory: (id: string) =>
    api.get<{ messages: unknown[] }>(
      `/copilot/sessions/${id}/history`
    ).then(r => r.data),

  clearSession: (id: string) =>
    api.delete(`/copilot/sessions/${id}`).then(r => r.data),
};

export default api;