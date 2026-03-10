/**
 * GameBridge: Event bus between Phaser scenes and React components.
 * Uses a simple EventTarget-based pub/sub system.
 */

type BridgeListener = (data: unknown) => void;

class GameBridgeClass {
  private listeners: Map<string, BridgeListener[]> = new Map();

  emit(event: string, data: unknown = {}): void {
    const handlers = this.listeners.get(event) || [];
    handlers.forEach((h) => h(data));
  }

  on(event: string, handler: BridgeListener): () => void {
    const handlers = this.listeners.get(event) || [];
    handlers.push(handler);
    this.listeners.set(event, handlers);
    // Return unsubscribe function
    return () => this.off(event, handler);
  }

  off(event: string, handler: BridgeListener): void {
    const handlers = this.listeners.get(event) || [];
    this.listeners.set(event, handlers.filter((h) => h !== handler));
  }
}

export const GameBridge = new GameBridgeClass();

// Event names: only Phaser → React events remain.
// Agent/task state is synced to Phaser via Zustand store subscription in OfficeScene.
export const BRIDGE_EVENTS = {
  WORKSTATION_CLICKED: 'workstation:clicked',
  AGENT_CLICKED: 'agent:clicked',
  WHITEBOARD_CLICKED: 'whiteboard:clicked',
  FILING_CABINET_CLICKED: 'filing_cabinet:clicked',
} as const;
