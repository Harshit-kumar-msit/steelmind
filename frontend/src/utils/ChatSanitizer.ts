import type { Citation, ActionButton, ChatMessage } from "../types";

export function sanitizeCitations(input: any): Citation[] {
  if (!Array.isArray(input)) return [];
  
  return input.filter((c): c is Citation => {
    return c && typeof c === "object";
  });
}

export function sanitizeActions(input: any): ActionButton[] {
  if (!Array.isArray(input)) return [];

  return input.filter((a): a is ActionButton => {
    return a && typeof a === "object" && "label" in a;
  });
}

export function sanitizeMessage(msg: any): ChatMessage {
  return {
    ...msg,
    citations: sanitizeCitations(msg.citations),
    actions: sanitizeActions(msg.actions),
  };
}