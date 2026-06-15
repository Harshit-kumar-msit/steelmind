// src/types/index.ts
// Central type definitions — import from here everywhere.

export interface Equipment {
  equipment_id:              string;
  name:                      string;
  plant_area_code:           string;
  equipment_type:            string;
  criticality:               'A' | 'B' | 'C';
  status:                    'operational' | 'degraded' | 'warning' | 'critical' | 'offline' | 'maintenance';
  rul_days:                  number | null;
  degradation_index:         number | null;
  anomaly_score:             number | null;
  priority_score:            number | null;
  last_health_update:        string | null;
  maintenance_interval_days: number;
  last_maintenance_date:     string | null;
}

export interface EquipmentDetail extends Equipment {
  manufacturer:     string;
  model_number:     string;
  rated_power_kw:   number | null;
  rated_speed_rpm:  number | null;
  install_date:     string | null;
  sensor_config:    SensorConfig;
  open_alerts:      AlertSummary[];
  health_history:   HealthSnapshot[];
  notes:            string;
}

export interface SensorConfig {
  normal:   Record<string, number>;
  warning:  Record<string, number>;
  critical: Record<string, number>;
}

export interface HealthSnapshot {
  timestamp:         string;
  anomaly_score:     number;
  degradation_index: number;
  rul_days:          number;
  priority_score:    number;
}

export interface SensorReading {
  time:  string;
  value: number | null;
}

export interface SensorSnapshot {
  vibration_rms_mm_s?: number;
  bearing_temp_c?:     number;
  lube_pressure_bar?:  number;
  motor_current_a?:    number;
  speed_rpm?:          number;
  outlet_temp_c?:      number;
  [key: string]:       number | undefined;
}

// ── Alerts ───────────────────────────────────────────────────────────────────

export interface Alert {
  id:              string;
  alert_code:      string;
  equipment_id:    string;
  severity:        'info' | 'warning' | 'critical';
  status:          'open' | 'acknowledged' | 'resolved';
  alert_type:      string;
  title:           string;
  description:     string;
  anomaly_score:   number | null;
  rul_days:        number | null;
  created_at:      string;
  acknowledged_at: string | null;
}

export interface AlertSummary {
  id:         string;
  alert_code: string;
  severity:   string;
  title:      string;
  created_at: string;
}

// ── Work Orders ───────────────────────────────────────────────────────────────

export interface WorkOrder {
  id:              string;
  wo_code:         string;
  equipment_id:    string;
  wo_type:         'preventive' | 'corrective' | 'predictive' | 'emergency';
  priority:        'P1' | 'P2' | 'P3' | 'P4';
  status:          'draft' | 'open' | 'in_progress' | 'completed' | 'cancelled';
  title:           string;
  description:     string;
  tasks:           string[];
  estimated_hours: number;
  scheduled_date:  string | null;
  assigned_to:     string[];
  parts_required:  PartRequirement[];
  ai_generated:    boolean;
  created_at:      string;
}

export interface PartRequirement {
  part_id: string;
  qty:     number;
}

// ── Spare Parts ───────────────────────────────────────────────────────────────

export interface SparePart {
  part_id:                  string;
  description:              string;
  quantity_on_hand:         number;
  reorder_point:            number;
  lead_time_days:           number;
  unit_cost_usd:            number;
  storage_location:         string;
  supplier:                 string;
  criticality:              string;
  equipment_compatibility:  string[];
  is_low_stock:             boolean;
}

// ── Chat / Copilot ────────────────────────────────────────────────────────────

export interface ChatMessage {
  id:        string;
  role:      'user' | 'assistant' | 'system';
  content:   string;
  timestamp: string;
  citations: Citation[];
  actions:   ActionButton[];
  isStreaming?: boolean;
}

export interface Citation {
  chunk_id:  string;
  doc_id:    string;
  title:     string;
  category:  string;
  preview:   string;
  rank:      number;
}

export interface ActionButton {
  action_type: string;
  label:       string;
  payload:     Record<string, string>;
}

// ── Dashboard Summary ─────────────────────────────────────────────────────────

export interface PlantSummary {
  total_equipment:       number;
  healthy:               number;
  warning:               number;
  urgent:                number;
  critical:              number;
  open_alerts:           number;
  critical_alerts:       number;
  avg_rul_critical_days: number;
  last_updated:          string;
}

// ── Anomaly ───────────────────────────────────────────────────────────────────

export interface AnomalyScore {
  equipment_id:    string;
  anomaly_score:   number;
  is_anomaly:      boolean;
  severity:        'normal' | 'warning' | 'critical';
  top_contributor: string;
  contributions:   Record<string, number>;
  z_scores:        Record<string, number>;
  sensor_values:   Record<string, number>;
}

// ── Reports ───────────────────────────────────────────────────────────────────

export interface WeeklyReport {
  report_type:  string;
  generated_at: string;
  content:      string;
  metadata:     Record<string, unknown>;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface AuthUser {
  user_id:      string;
  full_name:    string;
  role:         string;
  access_token: string;
}
