// src/store/index.ts
// Zustand stores for global state.
// Keep stores small — React Query handles server state (caching, refetch).
// Zustand handles UI state: selected equipment, active session, sidebar open, etc.

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser, Equipment } from '../types';

// ── Auth Store ─────────────────────────────────────────────────────────────

interface AuthState {
  user:    AuthUser | null;
  setUser: (u: AuthUser | null) => void;
  logout:  () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user:    null,
      setUser: (u) => {
        set({ user: u });
        if (u) localStorage.setItem('steelmind_token', u.access_token);
        else   localStorage.removeItem('steelmind_token');
      },
      logout: () => {
        localStorage.removeItem('steelmind_token');
        set({ user: null });
      },
    }),
    { name: 'steelmind-auth' }
  )
);

// ── UI Store ───────────────────────────────────────────────────────────────

interface UIState {
  sidebarOpen:         boolean;
  activeEquipmentId:   string;
  activePage:          string;
  setSidebarOpen:      (v: boolean) => void;
  setActiveEquipment:  (id: string) => void;
  setActivePage:       (page: string) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen:         true,
  activeEquipmentId:   '',
  activePage:          'health',
  setSidebarOpen:      (v) => set({ sidebarOpen: v }),
  setActiveEquipment:  (id) => set({ activeEquipmentId: id }),
  setActivePage:       (page) => set({ activePage: page }),
}));

// ── Chat Store ─────────────────────────────────────────────────────────────

import type { ChatMessage, Citation, ActionButton } from '../types';
import { v4 as uuidv4 } from 'uuid';

interface ChatState {
  sessionId:          string;
  messages:           ChatMessage[];
  focusedEquipmentId: string;
  isStreaming:        boolean;
  streamingMessageId: string | null;

  setFocusedEquipment: (id: string) => void;
  addUserMessage:      (content: string) => string;
  startAssistantMessage: () => string;
  appendToken:         (messageId: string, token: string) => void;
  finalizeMessage:     (messageId: string, citations: Citation[], actions: ActionButton[]) => void;
  setStreaming:        (v: boolean) => void;
  clearMessages:       () => void;
  loadHistory:         (messages: ChatMessage[]) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId:          uuidv4(),
  messages:           [],
  focusedEquipmentId: '',
  isStreaming:        false,
  streamingMessageId: null,

  setFocusedEquipment: (id) => set({ focusedEquipmentId: id }),

  addUserMessage: (content) => {
    const id = uuidv4();
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: 'user', content, timestamp: new Date().toISOString(), citations: [], actions: [] },
      ],
    }));
    return id;
  },

  startAssistantMessage: () => {
    const id = uuidv4();
    set((s) => ({
      streamingMessageId: id,
      isStreaming: true,
      messages: [
        ...s.messages,
        { id, role: 'assistant', content: '', timestamp: new Date().toISOString(),
          citations: [], actions: [], isStreaming: true },
      ],
    }));
    return id;
  },

  appendToken: (messageId, token) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, content: m.content + token } : m
      ),
    }));
  },

  finalizeMessage: (messageId, citations, actions) => {
    set((s) => ({
      isStreaming: false,
      streamingMessageId: null,
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, citations, actions, isStreaming: false } : m
      ),
    }));
  },

  setStreaming: (v) => set({ isStreaming: v }),

  clearMessages: () => set({ messages: [], sessionId: uuidv4() }),

  loadHistory: (messages) => set({ messages }),
}));

// ── Alert Count Store (for badge) ──────────────────────────────────────────

interface AlertCountState {
  openCount:    number;
  criticalCount:number;
  setCount:     (open: number, critical: number) => void;
}

export const useAlertCountStore = create<AlertCountState>((set) => ({
  openCount:    0,
  criticalCount:0,
  setCount:     (open, critical) => set({ openCount: open, criticalCount: critical }),
}));
